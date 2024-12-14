"""
OpenFDA
DAG auto-generated by Astro Cloud IDE.
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import pandas as pd
import requests

# Function to generate query URL for a specific month and year
def generate_query_url(year, month):
    start_date = f"{year}{month:02d}01"
    end_date = f"{year}{month:02d}{(datetime(year, month, 1) + timedelta(days=31)).replace(day=1) - timedelta(days=1):%d}"
    query = f"https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:%22sildenafil+citrate%22+AND+receivedate:[{start_date}+TO+{end_date}]&count=receivedate"
    return query

# Function to fetch data from the API and save it to XCom
def fetch_openfda_data(ds, ti, **context):
    from airflow.operators.python import get_current_context
    context = get_current_context()
    execution_date = context['dag_run'].execution_date
    year = execution_date.year
    month = execution_date.month

    query_url = generate_query_url(year, month)
    response = requests.get(query_url)

    if response.status_code == 200:
        data = response.json()
        df = pd.DataFrame(data['results'])
        df['time'] = pd.to_datetime(df['time'])
        # Group by week and sum the count column
        weekly_sum = df.groupby(pd.Grouper(key='time', freq='W'))['count'].sum().reset_index()
        weekly_sum.loc[:,"time"] = weekly_sum.loc[:,"time"].astype(str)
        print(weekly_sum.head())
    else:
        weekly_sum = pd.DataFrame([])  # Return empty DataFrame if request fails

    # Push the DataFrame to XCom
    ti.xcom_push(key='openfda_data', value=weekly_sum.to_dict())

def save_to_postgresql(ds, ti, **context):
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    # Retrieve the DataFrame from XCom
    data_dict = ti.xcom_pull(task_ids='fetch_openfda_data', key='openfda_data')

    if data_dict:
        df = pd.DataFrame.from_dict(data_dict)

        # Define PostgreSQL connection details
        pg_hook = PostgresHook(postgres_conn_id='postgres')
        engine = pg_hook.get_sqlalchemy_engine()
        # Save the DataFrame to the database
        df.to_sql('openfda_data', con=engine, if_exists='append', index=False)


# Define the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'fetch_openfda_data_monthly',
    default_args=default_args,
    description='Retrieve OpenFDA data monthly',
    schedule_interval='@monthly',
    start_date=datetime(2020, 1, 1),
    catchup=True,
    max_active_tasks=5
)


fetch_data_task = PythonOperator(
    task_id='fetch_openfda_data',
    provide_context=True,
    python_callable=fetch_openfda_data,
    dag=dag,
)

save_data_task = PythonOperator(
    task_id='save_to_postgresql',
    provide_context=True,
    python_callable=save_to_postgresql,
    dag=dag,
)

fetch_data_task >> save_data_task


