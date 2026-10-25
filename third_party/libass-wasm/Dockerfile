FROM docker.io/emscripten/emsdk:3.1.15@sha256:0f219e5040df37d257b29c618d410eb502f7d0876025e7e10c4a25b018a6019d

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        git \
        ragel \
        patch \
        libtool \
        itstool \
        pkg-config \
        python3 \
        python3-ply \
        gettext \
        autopoint \
        automake \
        autoconf \
        m4 \
        gperf \
        licensecheck \
    && rm -rf /var/lib/apt/lists/*

ENV EMCC_CORES=2
WORKDIR /code
CMD ["make"]
