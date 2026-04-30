FROM public.ecr.aws/lambda/python:3.11

WORKDIR ${LAMBDA_TASK_ROOT}

# Copy shared_lambda code
COPY shared_lambda/ ./shared_lambda/

# Copy ingestion lambda code
COPY ingestion_lambda/ .

# Install shared deps
COPY shared_lambda/requirements.txt ./shared_requirements.txt
RUN pip install --no-cache-dir -r shared_requirements.txt

# Install ingestion-specific deps
# Note: no voyageai — using boto3 bedrock (already in shared deps)
COPY ingestion_lambda/requirements.txt ./ingestion_requirements.txt
RUN pip install --no-cache-dir -r ingestion_requirements.txt

CMD ["handler.handler"]