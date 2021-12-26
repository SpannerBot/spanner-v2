FROM python:3.10.1-bullseye
WORKDIR /bot
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python3", "launcher.py"]
