import time
import logging
import pandas as pd
from typing import List
from elasticsearch7 import Elasticsearch, Transport, RequestsHttpConnection

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("export_jumpserver.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


class ESExporter:
    def __init__(self, es_hosts: List[str], username: str = None, password: str = None):
        """初始化ES连接（适配7.x版本）"""
        auth_kwargs = {}
        if username and password:
            auth_kwargs["http_auth"] = (username, password)

        self.es = Elasticsearch(
            hosts=es_hosts, **auth_kwargs,
            timeout=30,
            max_retries=3,
            retry_on_timeout=True,
            transport_class=Transport,
            connection_class=RequestsHttpConnection,
            connection_timeout=30
        )
        if not self.es.ping():
            raise ConnectionError("无法连接到Elasticsearch 7.x集群，请检查配置")
        logger.info("成功连接到Elasticsearch 7.x集群")

    def get_jumpserver_indices(self) -> List[str]:
        """获取所有jumpserver前缀的索引"""
        try:
            response = self.es.cat.indices(
                index="jumpserver*",
                h="index",
                format="json"
            )
            indices = [item["index"] for item in response]
            if not indices:
                logger.warning("未找到jumpserver前缀的索引")
            else:
                logger.info(f"找到{len(indices)}个jumpserver前缀索引: {indices}")
            return indices
        except Exception as e:
            logger.error(f"获取索引失败: {str(e)}", exc_info=True)
            raise

    def export_to_single_csv(self, output_file: str = "jumpserver_all.csv", batch_size: int = 1000) -> None:
        """合并所有jumpserver索引数据到单个CSV文件"""
        indices = self.get_jumpserver_indices()
        if not indices:
            logger.info("无索引可导出，退出")
            return

        # 初始化CSV文件（写入表头，仅第一次执行）
        first_index = indices[0]
        header_written = False

        for i, index in enumerate(indices, 1):
            logger.info(f"\n===== 开始处理第{i}/{len(indices)}个索引：{index} =====")

            try:
                # 获取当前索引文档总数
                count = self.es.count(index=index, body={"query": {"match_all": {}}})["count"]
                if count == 0:
                    logger.info(f"索引{index}无数据，跳过")
                    continue
                logger.info(f"索引{index}共{count}条数据")

                # 滚动查询参数
                scroll_time = "10m"
                query = {"query": {"match_all": {}}}
                response = self.es.search(
                    index=index,
                    body=query,
                    scroll=scroll_time,
                    size=batch_size
                )
                scroll_id = response["_scroll_id"]
                hits = response["hits"]["hits"]
                total_processed = len(hits)

                # 处理数据并写入CSV
                while len(hits) > 0:
                    # 提取_source数据
                    data_list = [hit["_source"] for hit in hits]
                    df = pd.DataFrame(data_list)

                    # 写入CSV（首次写入表头，后续追加）
                    if not header_written:
                        df.to_csv(output_file, mode="w", index=False, encoding="utf-8")
                        header_written = True
                    else:
                        # 确保列对齐（不同索引字段不同时，缺失字段用NaN填充）
                        existing_df = pd.read_csv(output_file, nrows=0)  # 仅读表头获取现有列
                        df = df.reindex(columns=existing_df.columns, fill_value=None)
                        df.to_csv(output_file, mode="a", header=False, index=False, encoding="utf-8")

                    # 进度提示
                    progress = (total_processed / count) * 100
                    logger.info(f"索引{index}：已处理{total_processed}/{count}条（{progress:.2f}%）")

                    # 继续滚动查询
                    response = self.es.scroll(scroll_id=scroll_id, scroll=scroll_time)
                    scroll_id = response["_scroll_id"]
                    hits = response["hits"]["hits"]
                    total_processed += len(hits)

                # 释放滚动上下文
                self.es.clear_scroll(scroll_id=scroll_id)
                logger.info(f"索引{index}处理完成")

            except Exception as e:
                logger.error(f"处理索引{index}失败: {str(e)}", exc_info=True)
                continue  # 跳过错误索引，继续处理下一个

            time.sleep(1)  # 避免请求过于频繁

        logger.info(f"所有索引数据已合并导出至：{output_file}")


if __name__ == "__main__":
    # 配置参数（根据实际环境修改）
    ES_HOSTS = ["http://ip:9200"]
    ES_USERNAME = "elastic"  # 无认证则设为None
    ES_PASSWORD = "*****"  # 无认证则设为None
    BATCH_SIZE = 1000  # 每批查询数量
    OUTPUT_CSV = "jumpserver_all.csv"  # 合并后的CSV文件名

    try:
        exporter = ESExporter(
            es_hosts=ES_HOSTS,
            username=ES_USERNAME,
            password=ES_PASSWORD
        )
        exporter.export_to_single_csv(output_file=OUTPUT_CSV, batch_size=BATCH_SIZE)
    except Exception as e:
        logger.error(f"导出过程失败: {str(e)}", exc_info=True)
        exit(1)
