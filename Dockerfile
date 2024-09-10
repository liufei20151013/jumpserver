FROM debian:buster-slim AS build-xpack

COPY apps/xpack /opt/xpack

ARG APT_MIRROR=http://mirrors.ustc.edu.cn

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=xpack \
    sed -i "s@http://.*.debian.org@${APT_MIRROR}@g" /etc/apt/sources.list \
    && rm -f /etc/apt/apt.conf.d/docker-clean \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && apt-get update \
    && apt-get install -y --no-install-recommends wget ca-certificates \
    && mkdir -p /opt/xpack/plugins/license/bin \
    && wget -O /opt/xpack/plugins/license/bin/fit2license https://fit2cloud-support.oss-cn-beijing.aliyuncs.com/xpack-license/validator_linux_amd64 \
    && chmod 755 /opt/xpack/plugins/license/bin/fit2license \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.11-slim-bullseye AS stage-build
ARG TARGETARCH

ARG VERSION
ENV VERSION=$VERSION

WORKDIR /opt/jumpserver
ADD . .
RUN cd utils && bash -ixeu build.sh

FROM python:3.11-slim-bullseye
ARG TARGETARCH

ARG BUILD_DEPENDENCIES="              \
        g++                           \
        make                          \
        pkg-config"

ARG DEPENDENCIES="                    \
        freetds-dev                   \
        libpq-dev                     \
        libffi-dev                    \
        libjpeg-dev                   \
        libkrb5-dev                   \
        libldap2-dev                  \
        libsasl2-dev                  \
        libssl-dev                    \
        libxml2-dev                   \
        libxmlsec1-dev                \
        libxmlsec1-openssl            \
        freerdp2-dev                  \
        libaio-dev"

ARG TOOLS="                           \
        ca-certificates               \
        curl                          \
        default-libmysqlclient-dev    \
        default-mysql-client          \
        locales                       \
        nmap                          \
        openssh-client                \
        sshpass                       \
        telnet                        \
        vim                           \
        wget"

ARG APT_MIRROR=http://mirrors.ustc.edu.cn

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked,id=core \
    sed -i "s@http://.*.debian.org@${APT_MIRROR}@g" /etc/apt/sources.list \
    && rm -f /etc/apt/apt.conf.d/docker-clean \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && apt-get update \
    && apt-get -y install --no-install-recommends ${BUILD_DEPENDENCIES} \
    && apt-get -y install --no-install-recommends ${DEPENDENCIES} \
    && apt-get -y install --no-install-recommends ${TOOLS} \
    && mkdir -p /root/.ssh/ \
    && echo "Host *\n\tStrictHostKeyChecking no\n\tUserKnownHostsFile /dev/null\n\tCiphers +aes128-cbc\n\tKexAlgorithms +diffie-hellman-group1-sha1\n\tHostKeyAlgorithms +ssh-rsa" > /root/.ssh/config \
    && echo "set mouse-=a" > ~/.vimrc \
    && echo "no" | dpkg-reconfigure dash \
    && echo "zh_CN.UTF-8" | dpkg-reconfigure locales \
    && sed -i "s@# export @export @g" ~/.bashrc \
    && sed -i "s@# alias @alias @g" ~/.bashrc \
    && rm -rf /var/lib/apt/lists/*

COPY --from=stage-build /opt/jumpserver/release/jumpserver /opt/jumpserver
WORKDIR /opt/jumpserver

ARG PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple/
RUN --mount=type=cache,target=/root/.cache \
    set -ex \
    && echo > /opt/jumpserver/config.yml \
    && pip install poetry -i ${PIP_MIRROR} \
    && poetry config virtualenvs.create false \
    && poetry install

COPY --from=build-xpack /opt/xpack /opt/jumpserver/apps/xpack

VOLUME /opt/jumpserver/data
VOLUME /opt/jumpserver/logs

ENV LANG=zh_CN.UTF-8

EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
