FROM ubuntu

RUN apt update && \
    apt install -y \
    python3 \
    pip \
    git
RUN apt-get clean

RUN mkdir /usr/src/stellarhector
WORKDIR /usr/src/stellarhector

COPY ./requirements.txt .

RUN pip install -r requirements.txt

RUN git config --global --add safe.directory /usr/src/stellarhector/data/archive
RUN git config --global user.email "archive@stellarvector.be"
RUN git config --global user.name "Stellar Vector Archive"

RUN groupadd -g 1000 sv-archiver
RUN useradd -ms /bin/bash -u 1000 -g 1000 sv-archiver

ENV PYTHONPATH=/usr/src/stellarhector
ENV GIT_PYTHON_REFRESH=0
