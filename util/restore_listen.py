import boto3
from boto3.dynamodb.conditions import Key, Attr
import botocore
import json
import time

###############################
###      AWS FUNCTIONS     ###
###############################

import aws

###############################
###          MAIN          ###
###############################

def main():
  # connect to SQS
  sqs = aws.get_sqs()
  queue_name = aws.SQS_RESTORE_RESULTS_QUEUE
  queue = aws.get_queue(sqs, queue_name)

  # loop for SQS messages
  while True:
    print("Asking SQS for up to 10 messages...")
    # Get messages
    messages = queue.receive_messages(WaitTimeSeconds=10)

    if len(messages) > 0:
      print("Received {0} messages...".format(str(len(messages))))
      # Iterate each message
      for message in messages:
        # get glacier restore job id
        message_data = json.loads(json.loads(message.body)['Message'])
        restore_job_id = message_data['JobId']
        print("Restore job id: " + restore_job_id)

        # get archive data
        glacier = aws.get_glacier_client()
        archive_data = aws.get_archive_data(glacier, restore_job_id)

        # get original annotation job id - stored as archive description
        job_id = archive_data['archiveDescription']

        # get annotations table
        table_name = aws.DYNAMODB_ANNOTATIONS_TABLE
        table = aws.get_table(table_name)

        # get annotation details for job
        annotation_details = aws.get_annotation_details(table, job_id)

        # put archive data in S3
        s3 = aws.get_s3()
        bucket = aws.S3_RESULTS_BUCKET
        key = annotation_details['s3_key_result_file']
        data = archive_data['body']
        aws.put_data_in_S3(s3, bucket, key, data)

        # update annotations db - set result file location as S3
        result_file_location = 'S3'
        aws.set_result_file_location(table, job_id, result_file_location)

        print("Restore process complete.")

        # Delete the message from the queue (only if processed)
        print ("Deleting message...")
        message.delete()

main()
