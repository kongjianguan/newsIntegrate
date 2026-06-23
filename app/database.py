from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import scoped_session, sessionmaker


def get_engine(db_path: str) -> Engine:
    # 构造 SQLite 数据库连接 URL
    url = f"sqlite:///{db_path}"
    engine = create_engine(url, echo=False)

    # 监听数据库连接事件，在每次新建连接时启用 WAL 模式以提升并发读写性能
    @event.listens_for(engine, "connect")
    def set_wal_mode(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    return engine


def get_session(engine: Engine) -> scoped_session:
    # 创建线程安全的 scoped session，每个线程获取独立的 session 实例
    return scoped_session(
        sessionmaker(bind=engine, autocommit=False, autoflush=False)
    )


def init_db(engine: Engine) -> None:
    # 根据 ORM 模型定义，在数据库中自动创建所有缺失的表
    from app.models import Base
    Base.metadata.create_all(bind=engine)
