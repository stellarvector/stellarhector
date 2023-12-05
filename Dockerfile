FROM python:3.11-slim

ENV PYTHONPATH=/usr/src/stellarhector
ENV GIT_PYTHON_REFRESH=0

# Install system dependencies
RUN apt update && \
    apt install -y \
    git
RUN apt-get clean

# Add user
RUN groupadd -g 1000 sv-archiver &&\
    useradd -ms /bin/bash -u 1000 -g 1000 sv-archiver

# Prepare working directory
USER sv-archiver
WORKDIR /usr/src/stellarhector

# Install python dependencies
COPY ./requirements.txt .
RUN pip install -r requirements.txt

# Git config
RUN git config --global --add safe.directory /usr/src/stellarhector/data/archive &&\
    git config --global user.email "archive@stellarvector.be" &&\
    git config --global user.name "Stellar Vector Archive"

CMD ["python3", "main.py"]
