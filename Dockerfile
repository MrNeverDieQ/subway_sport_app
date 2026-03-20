FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV BUILDOZER_WARN_ON_ROOT=0

RUN apt-get update && apt-get install -y \
    git zip unzip autoconf libtool pkg-config cmake \
    libffi-dev libssl-dev libsqlite3-dev liblzma-dev \
    python3 python3-pip python3-venv ccache \
    openjdk-17-jdk wget lbzip2 patch \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --upgrade pip && pip3 install buildozer cython==0.29.36

WORKDIR /app
COPY . .

CMD ["bash", "-c", "yes | buildozer android debug && cp bin/*.apk /output/"]
