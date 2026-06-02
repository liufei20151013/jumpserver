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
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQCdJaXv3A7mADekl99KT6CfCsPrjEJJymS8kel2K2JlkXl0VZ2yOhAEoPj0CY427fS36wmIDtnypt6nbuHEXdEtGolejASOSs4DFBVdoSyT3Nr7KO9oAOyzS84RrVXZKgW9Z+6uVHRjLKYFSYiRV6OzjqLnJsS3bIoN0GciRSDp1Sj9tMxJRYwpCN2Eop4KtyleWarUoHIokPkPZsowvMwTZ9MgUTFb28DVB7XlS3/qIg0hDn8abEzhJwS+tbzJr3936rfm9rSa0bG52T0vu9NLz7ePmDd1qVcHPkxiT4uKxZN6T8Rc0cPWYsIwVifQfvpe+BvxpXCZ9efPMRfLYDhJAgMBAAECggEABaZgHizTA01wMrR8JHOS8ozkSOB41KbYctgrJOK/7adqjrZyTkFcqJHyCXIbgRmSkhc69z+TcfAycqIfr1vxJJY+6J2Pn18Mo5sx/nUIQYOwAtYwr1RTLkoULVoGS2HBpZLqR63FJnipOmjvpkwYmGDRNg7UhUS7fO4oexixq35+PeMTcDZU9F8dHo4IiUtMPtB9CYmxmM7TwgrdumV/yXL2uWRF9O1I40IAGo0hMUXGPYTO06Tq1KGk74BYFL86BICltOKBvU3SOpBdKFjG5/Rwbuk5p8WsdxFuhC+mxPgIv92t3QeGrJ+WEgg8jXxbVj0GpXalQHZEYNuNDtX04QKBgQDX26QqS6ooO61re3wHfHsX5CMJxOwVX0e6f8zw0BkBixP3EtDFpC6De6EKe4DGk5cLS9NLWwe3ixS2tuWdRqoPEkYKAQlCINguQgjtQ8WnuXYOlGaTF7ozRI1bsc5DhuDdQLQEKdYvXrzoaY9FY1z+w8s6C8jK9i9F22vkeFDeuQKBgQC6XvRSbfkif9xNUmO4LGp00rVT8jV5mtINHQvRXQeeNchkXcrOZtgYDSuGtkgFpWyqgMesMDJPQONVs5S9ClXINqKse3UNdIIwLN0+it2ByQQ/lSE6p0oiE866PpH2pwxtAfYstw4w2Usb9PkR/Vg3ka7//owkqfCIkc4sTUXeEQKBgQC8BsAec6B5wVoTmRH193HF4ty+gsFe8Isrom1jivFtTbeLbeFbd+NodsVVuzT2RNO6bEdWianUMJtPeUvTzx0NWc6WokZtSuzkhnL+Mh23Ny7mDlC3amCwjdNQfzZ7zb6MG/Ny+Ppwcua80E6Tk7UK2oRpQKCcYwvUnwiBkGhpSQKBgD64xjEXocjijxnWqIjLKei3IR9nXGfYmuie5eNIE9BC+XYNurtMEV3G0Oc9YW/FBJU9UfW5IrVZeSjWjzAv0j7XZFf4FKS6mTXtY2gxA+sx46QiZFSBCIn/cIttk2IXRi9Jgbf6w2PdPVHjWA+d25qYBPVSjYepSbIsn955AxKBAoGBAKQaFGX+ZhYElLXItO/oDyJrhERJAUErZS0dBBua40AHp+5Efrh819HiZEcoJHRYwk+DUDBJgwpa60jzwrQrKDzIxB/P2LsckT/s5X3EhyB5efZknnQ3XneDEm6pEa15PESF73PznX28UMLGMAha5CkpyI2N+DEApjlC/57FeVS7
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
