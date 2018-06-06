import boto3
import botocore
import os
from subprocess import Popen
import json

###############################
###      AWS FUNCTIONS     ###
###############################

import aws

###############################
###     HELPER FUNCTIONS    ###
###############################

# get filename from key
def extract_filename(key):
  filename = key[key.rfind('/')+1:]
  return filename

# get job id from key
def extract_job_id(key):
  user_job_id_filename = key[key.find('/')+1:]
  job_id_filename = user_job_id_filename[user_job_id_filename.find('/')+1:]
  job_id = job_id_filename[:job_id_filename.rfind('/')]
  return job_id

# get prefix from key
def extract_prefix(key):
  cnet_user_job_id = key[:key.rfind('/')+1]
  return cnet_user_job_id

# create local job directory
def create_local_job_directory(job_directory):
  try:
    os.makedirs(job_directory)
  except:
    print("There was an error creating an internal directory to process the job.")

# call anntools using Popen
def run_anntools(run_file, key, job_file_path, job_id, job_directory, key_prefix, output_bucket):
  try:
    Popen(['python', run_file, job_file_path, job_id, job_directory, key_prefix, output_bucket], stdin=None, stdout=None, stderr=None, shell=False)
  except:
    print("There was an error starting the annotation process on this job when calling run.py.")

###############################
###         RUN JOB         ###
###############################

# run the annotation job
def run_job(job_data):
  # get key fields
  job_id = job_data['job_id']
  bucket = job_data['s3_inputs_bucket']
  key = job_data['s3_key_input_file']
  filename = job_data['input_file_name']

  # make sure key fields are defined
  if job_id is None or bucket is None or key is None or filename is None:
    print("Error: did not receive valid job id, bucket, key, or filename.")

  # define a directory and file path for the job
  job_directory = "data/jobs/" + job_id + "/"
  job_file_path = job_directory + filename

  # create local directory for job
  create_local_job_directory(job_directory)

  # connect to s3
  s3 = aws.get_s3()

  # download the file from s3
  aws.download_file_from_s3(s3, bucket, key, job_file_path)

  # run anntools
  run_file = 'run.py'
  key_prefix = extract_prefix(key)
  output_bucket = aws.S3_RESULTS_BUCKET
  run_anntools(run_file, key, job_file_path, job_id, job_directory, key_prefix, output_bucket)

  # success
  print("Anntools called successfully for job id: " + str(job_id))

###############################
###          MAIN          ###
###############################

def main():
  # connect to SQS
  sqs = aws.get_sqs()
  queue_name = aws.SQS_JOB_REQUESTS_QUEUE
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
        job_data = json.loads(json.loads(message.body)['Message'])
        print("Job data received:\n" + str(job_data))
        print("Starting job...")
        run_job(job_data)

        # Delete the message from the queue
        print ("Deleting message...")
        message.delete()

main()
