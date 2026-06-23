from apscheduler.schedulers.background import BackgroundScheduler


class SchedulerWrapper:
    """封装 APScheduler BackgroundScheduler，提供定时抓取的启停和重载功能"""

    def __init__(self):
        self._scheduler = None

    def start(self, config: dict, config_path: str, db_path: str):
        """启动定时调度器：添加间隔任务，可选择在启动时立即执行一次"""
        self._scheduler = BackgroundScheduler()
        interval = config.get("schedule", {}).get("interval_minutes", 30)

        from app.pipeline import run_pipeline

        # 将定时执行逻辑包装为无参函数，确保每次执行时重新加载配置
        def job():
            from app.config import load_config
            cfg = load_config(config_path)
            run_pipeline(db_path, cfg)

        # 添加周期性抓取任务
        self._scheduler.add_job(job, "interval", minutes=interval, id="fetch_job")

        # 根据配置决定是否启动后立即执行一次（默认启用）
        if config.get("schedule", {}).get("startup_fetch", True):
            self._scheduler.add_job(job, id="startup_fetch")

        self._scheduler.start()

    def restart(self, config: dict, config_path: str, db_path: str):
        """在不停止调度器的情况下，移除旧任务并以新间隔添加新任务"""
        if self._scheduler:
            self._scheduler.remove_job("fetch_job")
            interval = config.get("schedule", {}).get("interval_minutes", 30)

            from app.pipeline import run_pipeline

            def job():
                from app.config import load_config
                cfg = load_config(config_path)
                run_pipeline(db_path, cfg)

            self._scheduler.add_job(job, "interval", minutes=interval, id="fetch_job")

    def shutdown(self):
        """停止调度器并释放资源，不等待正在执行的任务"""
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
