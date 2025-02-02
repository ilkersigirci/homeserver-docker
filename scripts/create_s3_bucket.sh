#!/bin/bash

awslocal s3api \
    create-bucket --bucket ${CREATED_BUCKET_NAME} \
    --create-bucket-configuration LocationConstraint=$APP_AWS_REGION \
    --region $APP_AWS_REGION

echo '{"CORSRules":[{"AllowedHeaders":["*"],"AllowedMethods":["GET","POST","PUT"],"AllowedOrigins":["*"],"ExposeHeaders":["ETag"]}]}' > cors.json

awslocal s3api put-bucket-cors --bucket ${CREATED_BUCKET_NAME} --cors-configuration file://cors.json
