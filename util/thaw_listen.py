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
  queue_name = aws.SQS_THAW_REQUESTS_QUEUE
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
        # get user id
        user_id = json.loads(json.loads(message.body)['Message'])
        print("User id: " + str(user_id))

        # get glacier connection
        glacier = aws.get_glacier_client()

        # connect to the database
        table_name = aws.DYNAMODB_ANNOTATIONS_TABLE
        table = aws.get_table(table_name)

        # get annotations for user
        annotations = aws.get_annotations(table, user_id)
        print("Identified annotations in db for user.")

        # loop through each annotation
        for annotation in annotations:
          # get the job id
          job_id = annotation['job_id']
          print('Evaluating job id: ' + str(job_id))

          # set user role to premium
          user_role = 'premium_user'
          aws.set_user_role(table, job_id, user_role)

          # check if annotation is archived in glacier
          if annotation['result_file_location'] == 'Glacier':
            # create a request to thaw
            print("Data for this job is in Glacier.")
            archive_id = annotation['results_file_archive_id']
            tier = 'Expedited' # will auto-try Standard if Expeditied fails
            aws.request_restore(glacier, archive_id, tier)

            # update annotations db - show that file is being restored
            result_file_location = 'restoring from archive...'
            aws.set_result_file_location(table, job_id, result_file_location)
          else:
            print("Data for this job is not in Glacier.")

        # Delete the message from the queue (only if processed)
        print ("Deleting message...")
        message.delete()

main()
