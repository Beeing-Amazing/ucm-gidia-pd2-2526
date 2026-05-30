from airflow.decorators import dag, task
from datetime import datetime

@dag(start_date=datetime(2024, 1, 1), schedule=None, catchup=False)
def test_dag():
    @task
    def hello():
        print("hello")

    hello()

test_dag()
