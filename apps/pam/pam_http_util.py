import json
import time
import requests
from typing import Any, TypeVar, Type

from pam.open_api_sign_util import OpenApiSignUtil

T = TypeVar('T')


class PamHttpUtil:
    @staticmethod
    def post(url: str, result_class: Type[T], api_key: str) -> T:
        """无参数的POST请求"""
        return PamHttpUtil.post_with_param(url, None, result_class, api_key)

    @staticmethod
    def post_with_param(
            url: str,
            param: Any,
            result_class: Type[T],
            api_key: str
    ) -> T:
        """带参数的POST请求，生成签名并调用接口"""
        if param is None:
            param = {}

        print(f"向pam发送请求url: {url}")

        param_dict = json.loads(json.dumps(param))
        param_dict["apiKey"] = api_key
        # param_dict["requestTime"] = 1774335304026  # 毫秒级时间戳
        # print(time.time() * 1000)
        param_dict["requestTime"] = int(time.time() * 1000)  # 毫秒级时间戳

        # 生成签名
        try:
            # 私钥 注意格式
            private_key = """-----BEGIN PRIVATE KEY-----
MIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQCrQU480Ry/izMvw4/uZlW+HNBbLr6G0x52JnNXpQQ7ZH+9OLgAMtT6gsg1YiLXhqCFbI962fhweUIIabbVmc7ZGpFnA8wPZNOu6nAWO0sEErTFSEaUtUOPlI2fXgxLI4L7jASv6OwLQZjaQn5/bdIDsxAa+qnMekFFdGAdrysNH22G0a2bQYBSlxlrV+cHgK1vUNWXBJHU05Gv/bVuGp4NcJbkt14XcthXCXU0ZBhBzuWQovIyWokI54rIFT4lsxBCJ5IFNvMYTfCMdLOJQRylZ05pjly8+FAC8DuxaobBYP/1n4OKv1pDSrmb/oWf+BOFNqpjP+bCtFXe2NSd4lixAgMBAAECggEAAluwqovY2u6dVKNbT1WliTvTduj3rsq4DvmQMakUHAcCDwqJlpecmQs9W2ZTu17nRZURS/hVyGM0EIJ3pfzzZSgNb+Mkj4L0ewJviw/TlG2XQ4bvcV9mW/MYSOUyM0Psux7iRuOUwgIsCxfarvGlwF8qKevxE/+sN8sOooQBqlFiY2E0vDAmXiZ07j0U0wpSsKvRK7fxc7TvulZOxOEnLreOtcge2QOKsqKTCLrOSEn6dV4+5eywd/ncnD6LGTSCyA9GJCvtX75R60DdQhWkkZQVsr6vTTkiTy7w4Hvat3pluIC5V0rrKPTEv07CMWe+eoBgcIzQg+OsMI7sxotvoQKBgQDX2gGjr+l/RixnEZzDeWsNx5lZYVaBNtB9A75x5Da+eRlu4DFI+npw9k1YAUsnbN03r9knsvxJEFjsqQ5Y3/ZoUY9MSZ7VG1pdiQ7h5slOxMPs0Dj6sytLiZ6rsba/qcKGQHl5mfP2q1X1w9m4enekk2R3f7wv4QfKzDucK/Lq4QKBgQDLG8q9jURO50T/fY843fxz8/Ph05ofrjIMNYTAiJUeL0QVAPkBaapHl2g417prgzl8Rz5pqZfm4ppCZI4PBsPpShi9CLeKAKe3O2oSHVPtzJhzv9cdu+EK+rXXuCZ3w36TjOrvyNQySYWu/X+qi3KsLzmP8ANHexbqyIrLD6J30QKBgFriFdKf3MaT+1oiVkkPtH2GzxCNJWkedUZN7z/xAQPN5WGDz/yUSj2J1yL42HXvJm2uAtbuS79PvMFYpQvSsONXg+hxDwlXjQLZFIUVMSmTO5NYUMVt7wrNFRvhpbqpdZglSYBjzA7OMVFbdy5vkjSfQqv2Anx+WVOQDoFBF/TBAoGAJ5alL8knNVHyqvHoRqdOG7PDJ5M9CUvEyYhs9bIpjpab6JQl9NaJsCac0+eImIgdXlHsol/CEei9NI+w+NDSwtgEdmQKkkWKazaTeDBrOYCVfoo3/b2vIZq4cvGb3eAm/c+Lw20bnymhevhCOBWyJkmWKK4ZlYcyclTgaLAFdOECgYBKtbMZwNqwNtkrTaEeU6S+faQUv2N/zTMfskShaBvCkiAGg504zGdYnWpYfqfDWLfjm4LiDIU4rXtKWxBksw6oGD0jcxuMQR5JT6RL7Q/oYv7N5YZkGczOn8bcHycMf2sAefvDkMxsbYAYvgJQbG7DrLhrev5j6dcWDD4VcrcHWw==
-----END PRIVATE KEY-----"""
            OpenApiSignUtil.fill_sign(param_dict, private_key)
        except Exception as e:
            print(f"生成签名异常: {e}")
            raise RuntimeError("生成签名异常，请重试") from e

        json_str = json.dumps(param_dict, ensure_ascii=False)
        # print(f"向 pam 发送请求参数: {json_str}")

        try:
            response = requests.post(
                url=url,
                data=json_str.encode("utf-8"),
                headers={"Content-Type": "application/json"},
                verify=False  # 忽略SSL证书验证（根据实际情况调整）
            )
        except Exception as e:
            raise RuntimeError(f"请求PAM服务失败: {e}") from e

        # print(f"pam返回：{response.text}")

        if response.status_code != 200:
            print(f"post status : {response.status_code}")
            raise RuntimeError("pam 服务状态异常")

        result = response.json()
        return result

def get_account():
    limit = 10
    base_param = {
        "pageNum": "",
        "pageSize": limit
    }

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    url = '{PAM_SERVER}/openapi/v1/account/info/list'.format(PAM_SERVER='')
    print("url: {}".format(url))

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        base_param["pageNum"] = current_page
        print("base_param: {}".format(json.dumps(base_param)))

        response = PamHttpUtil.post_with_param(
            url=url,
            param=base_param,
            result_class=dict,
            api_key=''
        )
        code = response["code"]

        if code != '1000':
            message = response["msg"]
            print("Search account failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            print("search account result: {}".format(json.dumps(result)))

        res = response["rows"]
        total_pages = res["total"] // limit + (1 if res["total"] % limit != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    print("search account result: {}".format(json.dumps(result)))


def get_asset():
    limit = 10
    base_param = {
        "pageNum": "",
        "pageSize": limit,
        "category": 'web'
    }

    result = {
        "result": True,
        "code": 0,
        "error": "",
        "message": "",
        "data": {
            "total": 0,
            "list": []
        }
    }

    url = '{PAM_SERVER}/openapi/v1/asset/info/list'.format(PAM_SERVER='')
    print("url: {}".format(url))

    total_pages = -1
    current_page = 1

    while total_pages == -1 or current_page <= total_pages:
        base_param["pageNum"] = current_page
        print("base_param: {}".format(json.dumps(base_param)))

        response = PamHttpUtil.post_with_param(
            url=url,
            param=base_param,
            result_class=dict,
            api_key=''
        )
        code = response["code"]

        if code != '1000':
            message = response["msg"]
            print("Search asset failed. current_page: {}, Error: {}".format(current_page, message))
            result["code"] = code
            result["error"] = message
            print("search asset result: {}".format(json.dumps(result)))

        res = response["rows"]
        total_pages = res["total"] // limit + (1 if res["total"] % limit != 0 else 0)

        result["data"]["total"] = res["total"]
        result["data"]["list"].extend(res["list"])
        current_page += 1

    print("search asset result: {}".format(json.dumps(result)))

if __name__ == '__main__':
    # get_account()
    get_asset()
