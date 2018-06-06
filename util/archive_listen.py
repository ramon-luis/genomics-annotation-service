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
###     HELPER FUNCTIONS    ###
###############################

# check if it is time to archive data
def is_time_to_archive(annotation_details):
  current_time = int(time.time())
  complete_time = annotation_details['complete_time']
  archive_time = int(complete_time) + int(aws.FREE_USER_DATA_RETENTION)
  return current_time > archive_time

# confirm if a user is free
def is_free_user(annotation_details):
  user_role = annotation_details['user_role']
  return user_role == 'free_user'

###############################
###          MAIN          ###
###############################

def main():
  # connect to SQS
  sqs = aws.get_sqs()
  queue_name =aws.SQS_ARCHIVE_REQUESTS_QUEUE
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
        # get job id
        job_id = json.loads(json.loads(message.body)['Message'])
        print("Job id: " + str(job_id))

        # connect to the database
        table_name = aws.DYNAMODB_ANNOTATIONS_TABLE
        table = aws.get_table(table_name)

        # get annotation details
        annotation_details = aws.get_annotation_details(table, job_id)

        # make sure user role is still free
        if not is_free_user(annotation_details):
          print("User role is no longer free.")
          # Delete the message from the queue (no need to archive)
          print ("Deleting message...")
          message.delete()

        # check if ready to be archived
        elif not is_time_to_archive(annotation_details):
          print("Not enough time has elapsed to archive this file.")
        else:
          # claim the archive job
          if aws.claim_archive_job(table, job_id):
            print("Archiving result file...")

            # get s3
            s3 = aws.get_s3()

            # get Glacier vault
            glacier_resource = aws.get_glacier_resource()
            vault = aws.get_vault(glacier_resource)

            # archive the result file
            archive_id = aws.archive_result_file(s3, vault, annotation_details)
            print("Result file archived")

            # update archive status
            result_file_location = 'Glacier'
            aws.set_result_file_location(table, job_id, result_file_location)
            aws.set_archive_id(table, job_id, archive_id)
            print("Archive status updated in annotations database.")

            # delete s3 result file
            bucket = annotation_details['s3_results_bucket']
            key = annotation_details['s3_key_result_file']
            aws.delete_s3_file(s3, bucket, key)
            print("S3 result file deleted")

            # Delete the message from the queue (only if processed)
            print ("Deleting message...")
            message.delete()

main()
