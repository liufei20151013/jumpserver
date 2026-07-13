ARG VERSION=v4.10.16

FROM registry.fit2cloud.com/jumpserver/xpack:${VERSION} AS build-xpack
#FROM jumpserver/core-base:20260122_035753 AS stage-build
FROM jumpserver/core-base:v4.10.16 AS stage-build

COPY pyproject.toml /opt/jumpserver/pyproject.toml
COPY --from=build-xpack /opt/xpack /opt/jumpserver/apps/xpack

ARG TOOLS="                           \
        g++                           \
        curl                          \
        postgresql-client"

RUN set -ex \
    && apt-get update \
    && apt-get -y install --no-install-recommends ${TOOLS} \
    && apt-get clean all \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/jumpserver

ADD . .

RUN echo > /opt/jumpserver/config.yml \
    && \
    if [ -n "${VERSION}" ]; then \
        sed -i "s@VERSION = .*@VERSION = '${VERSION}'@g" apps/jumpserver/const.py; \
    fi

RUN set -ex \
    && export SECRET_KEY=$(head -c100 < /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 48) \
    && . /opt/py3/bin/activate \
    && cd apps \
    && python manage.py compilemessages


FROM python:3.11-slim-trixie
ENV LANG=en_US.UTF-8 \
    PATH=/opt/py3/bin:$PATH

ARG DEPENDENCIES="                    \
        libldap2-dev                  \
        libx11-dev"

ARG TOOLS="                           \
        cron                          \
        ca-certificates               \
        default-libmysqlclient-dev    \
        openssh-client                \
        sshpass                       \
        nmap                          \
        bubblewrap                    \
        vim                           \
        wget                          \
        curl                          \
        iputils-ping                  \
        netcat-openbsd                \
        telnet                        \
        postgresql-client"

ARG APT_MIRROR=https://mirrors.ustc.edu.cn

RUN set -ex \
    && sed -i "s@http://.*.debian.org@${APT_MIRROR}@g" /etc/apt/sources.list.d/debian.sources \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && apt-get update > /dev/null \
    && apt-get -y install --no-install-recommends ${DEPENDENCIES} \
    && apt-get -y install --no-install-recommends ${TOOLS} \
    && mkdir -p /root/.ssh/ \
    && echo "Host *\n\tStrictHostKeyChecking no\n\tUserKnownHostsFile /dev/null\n\tCiphers +aes128-cbc\n\tKexAlgorithms +diffie-hellman-group1-sha1\n\tHostKeyAlgorithms +ssh-rsa" > /root/.ssh/config \
    && echo "no" | dpkg-reconfigure dash \
    && apt-get clean all \
    && rm -rf /var/lib/apt/lists/* \
    && echo "0 3 * * * root find /tmp -type f -mtime +1 -size +1M -exec rm -f {} \; && date > /tmp/clean.log" > /etc/cron.d/cleanup_tmp \
    && chmod 0644 /etc/cron.d/cleanup_tmp

COPY --from=stage-build /opt /opt
COPY --from=stage-build /usr/local/bin /usr/local/bin
COPY --from=stage-build /opt/jumpserver/apps/libs/ansible/ansible.cfg /etc/ansible/

WORKDIR /opt/jumpserver

VOLUME /opt/jumpserver/data

ENTRYPOINT ["./entrypoint.sh"]

EXPOSE 8080

STOPSIGNAL SIGQUIT

CMD ["start", "all"]
