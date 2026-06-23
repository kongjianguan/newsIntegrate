from contextlib import asynccontextmanager
from pathlib import Path

from datetime import datetime

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import or_

from app.config import load_config, save_config
from app.database import get_engine, get_session, init_db
from app.models import Item, Source
from app.pipeline import run_pipeline
from app.scheduler import SchedulerWrapper

# 项目根目录路径
BASE_DIR = Path(__file__).parent.parent
# SQLite 数据库文件路径
DB_PATH = str(BASE_DIR / "data" / "news.db")
# YAML 配置文件路径
CONFIG_PATH = str(BASE_DIR / "config.yaml")
# Jinja2 模板目录路径
TEMPLATES_DIR = str(BASE_DIR / "app" / "templates")

# 初始化 Jinja2 模板引擎，启用自动重载以便开发时即时生效
jinja_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), auto_reload=True)


def _render(template_name: str, context: dict) -> HTMLResponse:
    """渲染 Jinja2 模板并返回 HTMLResponse"""
    template = jinja_env.get_template(template_name)
    return HTMLResponse(template.render(context))

# 全局定时调度器实例，在应用启动和设置变更时控制
scheduler = SchedulerWrapper()


def get_db_session():
    """获取数据库引擎、初始化表结构、返回 scoped session 工厂"""
    engine = get_engine(DB_PATH)
    init_db(engine)
    return get_session(engine)


def _format_time(dt: datetime | None) -> str:
    """将 datetime 转为本地时间的友好显示格式：
       - 仅知道年份的（1月1日）只显示年份
       - 今年的显示 月-日 时:分
       - 往年的显示完整 年-月-日 时:分
    """
    if not dt:
        return ""
    local_dt = dt.astimezone()
    # 如果发布日期的月日都是 1 月 1 日，说明可能只有年份信息，只显示年份
    if local_dt.month == 1 and local_dt.day == 1:
        return str(local_dt.year)
    # 当前年份内的条目，显示紧凑格式
    if local_dt.year == datetime.now().year:
        return local_dt.strftime("%m-%d %H:%M")
    return local_dt.strftime("%Y-%m-%d %H:%M")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期管理：应用启动时加载配置并启动调度器，关闭时正确停止"""
    config = load_config(CONFIG_PATH)
    scheduler.start(config, CONFIG_PATH, DB_PATH)
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)
# 挂载静态文件目录，提供 CSS/JS/图片等资源
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    category: str = Query(default=""),
    source: str = Query(default=""),
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
):
    """首页：分页展示新闻条目，支持按分类、来源筛选和关键词搜索"""
    config = load_config(CONFIG_PATH)
    categories = config.get("preferences", {}).get("categories", [])
    session_cls = get_db_session()
    per_page = 20

    with session_cls() as s:
        # 基础查询：关联 Source 表以获取来源名称
        query = s.query(Item).join(Source, Item.source_id == Source.id)

        # 按分类过滤
        if category:
            query = query.filter(Item.category == category)
        # 按来源过滤
        if source:
            query = query.filter(Source.name == source)
        # 关键词搜索（至少 2 个字符），匹配标题、中文标题、摘要
        if q and len(q) >= 2:
            query = query.filter(
                or_(
                    Item.title.ilike(f"%{q}%"),
                    Item.title_cn.ilike(f"%{q}%"),
                    Item.summary.ilike(f"%{q}%"),
                )
            )

        total = query.count()
        total_pages = max(1, (total + per_page - 1) // per_page)
        # 按发布时间降序排列，空值排在最后
        items = (
            query.order_by(Item.published_at.desc().nullslast(), Item.fetched_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )

        # 获取所有来源列表，供侧边栏筛选使用
        sources = s.query(Source).order_by(Source.name).all()

        # 将 ORM 对象转为字典，便于模板渲染
        items_data = []
        for item in items:
            items_data.append({
                "id": item.id,
                "source_name": item.source.name,
                "title": item.title,
                "title_cn": item.title_cn,
                "url": item.url,
                "summary": item.summary,
                "category": item.category,
                "score": item.score,
                # 显示发布时间，若无法获得则使用抓取时间
                "published_at": _format_time(item.published_at) or _format_time(item.fetched_at),
                "fetched_at": _format_time(item.fetched_at),
            })

    return _render("index.html", {
        "request": request,
        "items": items_data,
        "categories": categories,
        "sources": sources,
        "current_category": category,
        "current_source": source,
        "query": q,
        "page": page,
        "total_pages": total_pages,
    })


@app.get("/sources", response_class=HTMLResponse)
async def sources_page(request: Request):
    """订阅源管理页面：展示所有已配置的订阅源"""
    config = load_config(CONFIG_PATH)
    session_cls = get_db_session()
    with session_cls() as s:
        db_sources = s.query(Source).order_by(Source.name).all()
    return _render("sources.html", {
        "request": request,
        "sources": db_sources,
    })


@app.post("/sources")
async def sources_add(request: Request, name: str = Form(...), url: str = Form(...)):
    """新增订阅源：通过表单提交名称和 URL，写入配置文件"""
    config = load_config(CONFIG_PATH)
    sources = config.get("sources", [])
    sources.append({"name": name, "url": url, "enabled": True})
    config["sources"] = sources
    save_config(config, CONFIG_PATH)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{index}/toggle")
async def sources_toggle(index: int):
    """切换指定订阅源的启用/禁用状态"""
    config = load_config(CONFIG_PATH)
    sources = config.get("sources", [])
    if 0 <= index < len(sources):
        sources[index]["enabled"] = not sources[index].get("enabled", True)
        config["sources"] = sources
        save_config(config, CONFIG_PATH)
    return RedirectResponse(url="/sources", status_code=303)


@app.post("/sources/{index}/delete")
async def sources_delete(index: int):
    """删除指定订阅源"""
    config = load_config(CONFIG_PATH)
    sources = config.get("sources", [])
    if 0 <= index < len(sources):
        del sources[index]
        config["sources"] = sources
        save_config(config, CONFIG_PATH)
    return RedirectResponse(url="/sources", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    """设置页面：展示 LLM 配置、调度间隔、偏好和保留天数"""
    config = load_config(CONFIG_PATH)
    return _render("settings.html", {
        "request": request,
        "config": config,
    })


@app.post("/settings")
async def settings_save(
    request: Request,
    llm_provider: str = Form(...),
    llm_api_key: str = Form(...),
    llm_base_url: str = Form(...),
    llm_model: str = Form(...),
    schedule_interval: int = Form(...),
    pref_description: str = Form(...),
    pref_categories: str = Form(...),
    retention_days: int = Form(...),
):
    """保存设置：更新 LLM、调度、偏好和保留天数配置，并重启调度器"""
    config = load_config(CONFIG_PATH)
    config.setdefault("llm", {})  # type: ignore
    config["llm"]["provider"] = llm_provider
    config["llm"]["api_key"] = llm_api_key
    config["llm"]["base_url"] = llm_base_url
    config["llm"]["model"] = llm_model
    config.setdefault("schedule", {})  # type: ignore
    config["schedule"]["interval_minutes"] = schedule_interval
    config.setdefault("preferences", {})  # type: ignore
    config["preferences"]["description"] = pref_description
    # 将逗号分隔的分类字符串拆分为列表，并去除空白
    config["preferences"]["categories"] = [c.strip() for c in pref_categories.split(",") if c.strip()]
    config["retention_days"] = retention_days
    save_config(config, CONFIG_PATH)

    # 设置变更后重启调度器，使新间隔立即生效
    scheduler.restart(config, CONFIG_PATH, DB_PATH)

    return _render("settings.html", {
        "request": request,
        "config": config,
        "message": "设置已保存",
    })


@app.post("/api/refresh")
async def api_refresh():
    """手动触发一次全量抓取和 LLM 处理管线"""
    config = load_config(CONFIG_PATH)
    run_pipeline(DB_PATH, config)
    return RedirectResponse(url="/", status_code=303)
