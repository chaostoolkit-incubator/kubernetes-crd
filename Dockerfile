FROM python:3.7-alpine

ADD requirements.txt requirements.txt
RUN apk add --no-cache --virtual build-deps gcc g++ linux-headers make \
        linux-headers musl-dev && \
    pip install --no-cache-dir -q -U pip && \
    pip install --no-cache-dir -r requirements.txt && \
    rm -rf /tmp/* /root/.cache && \
    apk del build-deps

RUN adduser --disabled-password --home /home/svc svc
USER svc
WORKDIR /home/svc
ADD controller.py controller.py

ENTRYPOINT ["kopf"]
CMD ["run", "--namespace", "chaostoolkit-crd", "controller.py"]
