FROM ubuntu

RUN apt update
RUN apt install python3 -y
RUN apt install pip -y
RUN mkdir /usr/src/stellarhector
WORKDIR /usr/src/stellarhector

COPY ./requirements.txt .
RUN pip install -r requirements.txt
ENV PYTHONPATH=/usr/src/stellarhector
ENV GIT_PYTHON_REFRESH=0
