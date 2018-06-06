import boto3
import botocore
import json

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
  queue_name = aws.SQS_JOB_RESULTS_QUEUE
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
        # get job data
        job_id = json.loads(json.loads(message.body)['Message'])
        print("Job id: " + str(job_id))

        # connect to the database
        table_name = aws.DYNAMODB_ANNOTATIONS_TABLE
        table = aws.get_table(table_name)

        # get annotation details
        annotation_details = aws.get_annotation_details(table, job_id)

        # send notification using ses
        print("Notifying user job complete...")
        ses = aws.get_ses()
        aws.notify_user(ses, annotation_details)

        # Delete the message from the queue
        print ("Deleting message...")
        message.delete()

main()
