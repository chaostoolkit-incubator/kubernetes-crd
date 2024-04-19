FROM ubuntu:rolling AS build-venv

ARG DEBIAN_FRONTEND=noninteractive

RUN groupadd -g 1001 svc && useradd -r -u 1001 -g svc svc

COPY pyproject.toml pdm.lock /home/svc/
RUN apt-get update && \
    apt-get install -y python3.11 && \
    apt-get install -y --no-install-recommends curl python3.11-venv build-essential gcc && \
    curl -sSL https://raw.githubusercontent.com/pdm-project/pdm/main/install-pdm.py | python3.11 - && \
    export PATH="$PATH:/root/.local/bin" && \
    pdm self update && \
    cd /home/svc/ && \
    pdm venv create python3.11 && \
    pdm use .venv && \
    pdm update --no-editable --prod --no-self --frozen-lockfile && \
    chown --recursive svc:svc /home/svc/.venv  && \
    apt-get remove -y build-essential gcc && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

FROM ubuntu:rolling

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y python3.11 && \
    groupadd -g 1001 svc && \
    useradd -m -u 1001 -g svc svc && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY --from=build-venv --chown=svc:svc /home/svc/.venv/ /home/svc/.venv

WORKDIR /home/svc
USER 1001
ENV PATH="/home/svc/.venv/bin:${PATH}" 

ADD --chown=svc:svc controller.py /home/svc/controller.py

ENTRYPOINT ["kopf"]
CMD ["run", "--namespace", "chaostoolkit-crd", "controller.py"]
