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

ENV PYTHONPATH=/usr/src/stellarhector
ENV GIT_PYTHON_REFRESH=0
