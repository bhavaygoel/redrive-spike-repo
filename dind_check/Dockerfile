FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir psycopg2-binary==2.9.10
COPY app/app.py .
EXPOSE 8092
CMD ["python", "app.py"]
