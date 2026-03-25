import base64
import json
from typing import Dict, Any, List
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend
from cryptography.exceptions import InvalidSignature


class OpenApiSignUtil:
    INDEX_NOT_FOUND = -1

    @staticmethod
    def fill_sign(param: Dict[str, Any], private_key_str: str) -> None:
        """生成签名并填充到param的apiSign字段"""
        sign = OpenApiSignUtil.generate_sign(param, private_key_str)
        print("apiSign: {}".format(sign))
        param["apiSign"] = sign

    @staticmethod
    def generate_sign(param: Any, private_key_str: str) -> str:
        """生成RSA-SHA256签名"""
        # 将任意对象转为字典并序列化排序
        params_map = json.loads(json.dumps(param))
        if not params_map:
            return ""

        # 生成待签名字符串
        src = OpenApiSignUtil.map_to_string(params_map)

        # 加载PKCS8格式的私钥
        private_key = serialization.load_pem_private_key(
            private_key_str.encode("utf-8"),
            password=None,
            backend=default_backend()
        )

        # 签名
        signature = private_key.sign(
            src.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        # Base64编码返回
        return base64.b64encode(signature).decode("utf-8")

    @staticmethod
    def verify(params: Any, application_public_key: str) -> bool:
        """验签"""
        try:
            # 解析参数为字典
            map_data = json.loads(json.dumps(params))
            api_sign = str(map_data.pop("apiSign"))
            param_str = OpenApiSignUtil.map_to_string(map_data)

            # 加载公钥
            public_key = serialization.load_pem_public_key(
                application_public_key.encode("utf-8"),
                backend=default_backend()
            )

            # 验签
            public_key.verify(
                base64.b64decode(api_sign),
                param_str.encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return True
        except InvalidSignature:
            return False
        except Exception as e:
            raise RuntimeError("签名解析异常!") from e

    @staticmethod
    def map_to_string(params_map: Dict[str, Any]) -> str:
        """字典排序后转为key=value&key=value格式字符串"""
        if not params_map:
            return ""

        # 排序key
        keys: List[str] = sorted(params_map.keys())
        sb = []
        for each_key in keys:
            str_val = str(params_map.get(each_key, "")).strip()
            if str_val:
                # 移除空格和双引号，拼接key=value
                clean_val = str_val.replace(" ", "").replace("\"", "")
                sb.append(f"{each_key}={clean_val}")
        # 拼接&并返回
        return "&".join(sb)

    @staticmethod
    def substring_before_last(s: str, separator: str) -> str:
        """截取最后一个分隔符之前的字符串"""
        if not s or not separator:
            return s
        pos = s.rfind(separator)
        return s[:pos] if pos != -1 else s

    @staticmethod
    def is_empty(cs: str) -> bool:
        """判断字符串是否为空"""
        return cs is None or len(cs) == 0
