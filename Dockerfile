FROM python:3.9-alpine

ADD requirements.txt requirements.txt
RUN apk add --no-cache --virtual build-deps gcc g++ linux-headers make \
        linux-headers musl-dev && \
    pip install --prefer-binary --no-cache-dir -q -U pip && \
    pip install --prefer-binary --no-cache-dir -r requirements.txt && \
    rm -rf /tmp/* /root/.cache && \
    apk del build-deps


RUN addgroup --gid 1001 svc
RUN adduser --disabled-password --home /home/svc --uid 1001 --ingroup svc svc

WORKDIR /home/svc
ADD controller.py controller.py
RUN chown svc:svc /home/svc/controller.py

# Any non-zero number will do, and unfortunately a named user will not,
# as k8s pod securityContext runAsNonRoot can't resolve the user ID:
# https://github.com/kubernetes/kubernetes/issues/40958
USER 1001

ENTRYPOINT ["kopf"]
CMD ["run", "--namespace", "chaostoolkit-crd", "controller.py"]
