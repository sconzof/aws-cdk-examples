# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from aws_xray_sdk.core import xray_recorder
from aws_xray_sdk.core import patch_all

patch_all()

import boto3
from botocore.exceptions import ClientError
import os
import json
import logging
import uuid
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb_client = boto3.client("dynamodb")


def put_item_with_retry(table, item, request_id, max_retries=3):
    """Put item to DynamoDB with exponential backoff retry logic."""
    for attempt in range(max_retries):
        try:
            dynamodb_client.put_item(TableName=table, Item=item)
            return True
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code in ['ProvisionedThroughputExceededException', 'ThrottlingException']:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) * 0.1
                    logger.warning(json.dumps({
                        "event": "dynamodb_throttled",
                        "request_id": request_id,
                        "attempt": attempt + 1,
                        "wait_time": wait_time,
                        "error_code": error_code
                    }))
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(json.dumps({
                        "event": "dynamodb_throttled_max_retries",
                        "request_id": request_id,
                        "error_code": error_code
                    }))
            raise
    return False


def handler(event, context):
    table = os.environ.get("TABLE_NAME")
    request_id = context.request_id
    
    # Log request context
    logger.info(json.dumps({
        "event": "request_received",
        "request_id": request_id,
        "source_ip": event.get("requestContext", {}).get("identity", {}).get("sourceIp"),
        "http_method": event.get("requestContext", {}).get("httpMethod"),
        "path": event.get("requestContext", {}).get("path"),
    }))
    
    try:
        if event["body"]:
            item = json.loads(event["body"])
            logger.info(json.dumps({
                "event": "processing_request",
                "request_id": request_id,
                "item_id": item.get("id"),
            }))
            
            year = str(item["year"])
            title = str(item["title"])
            id = str(item["id"])
            
            put_item_with_retry(
                table,
                {"year": {"N": year}, "title": {"S": title}, "id": {"S": id}},
                request_id
            )
            
            logger.info(json.dumps({
                "event": "dynamodb_write_success",
                "request_id": request_id,
                "table": table,
                "item_id": id,
            }))
            
            message = "Successfully inserted data!"
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": message}),
            }
        else:
            logger.info(json.dumps({
                "event": "processing_default_request",
                "request_id": request_id,
            }))
            
            default_id = str(uuid.uuid4())
            put_item_with_retry(
                table,
                {
                    "year": {"N": "2012"},
                    "title": {"S": "The Amazing Spider-Man 2"},
                    "id": {"S": default_id},
                },
                request_id
            )
            
            logger.info(json.dumps({
                "event": "dynamodb_write_success",
                "request_id": request_id,
                "table": table,
                "item_id": default_id,
            }))
            
            message = "Successfully inserted data!"
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"message": message}),
            }
    except Exception as e:
        logger.error(json.dumps({
            "event": "error",
            "request_id": request_id,
            "error_type": type(e).__name__,
            "error_message": str(e),
        }))
        raise
