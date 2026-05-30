FROM apache/airflow:3.2.1-python3.13

WORKDIR /opt/airflow

COPY airflow/requirements.txt .
COPY ./.env .

RUN pip install --no-cache-dir -r requirements.txt
