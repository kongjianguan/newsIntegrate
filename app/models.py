from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """自定义 SQLAlchemy 类型：入库时统一转为 UTC 无时区 datetime，出库时重新附加 UTC 时区"""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        # 写入数据库前，将有时区的 datetime 转为 UTC 再剥离时区信息
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        # 从数据库读取后，重新附加 UTC 时区
        if value is not None:
            return value.replace(tzinfo=timezone.utc)
        return value


class Base(DeclarativeBase):
    pass


class Source(Base):
    """RSS 订阅源表，存储每个订阅源的名称、URL、启用状态和抓取统计"""
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    url = Column(String(1024), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    last_fetched_at = Column(UTCDateTime, nullable=True)
    error_count = Column(Integer, default=0, nullable=False)

    items = relationship("Item", back_populates="source")


class Item(Base):
    """新闻条目表，存储从 RSS 抓取的原始内容及 LLM 处理后的结果"""
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    title = Column(String(1024), nullable=False)
    title_cn = Column(String(1024), nullable=True)
    url = Column(String(2048), unique=True, nullable=False)
    summary = Column(Text, nullable=True)
    category = Column(String(128), nullable=True)
    score = Column(Integer, nullable=True)
    published_at = Column(UTCDateTime, nullable=True)
    fetched_at = Column(UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    source = relationship("Source", back_populates="items")
