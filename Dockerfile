FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV BUILDOZER_WARN_ON_ROOT=0

RUN apt-get update && apt-get install -y \
    git zip unzip autoconf libtool \
    libffi-dev libssl-dev libsqlite3-dev \
    python3 python3-pip ccache \
    openjdk-17-jdk \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install buildozer cython

WORKDIR /app
COPY . .

RUN yes | buildozer android debug
