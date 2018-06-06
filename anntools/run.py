import boto3
from boto3.dynamodb.conditions import Key, Attr
from os import listdir
from os.path import isfile, join
import shutil
import time
import sys
import time
import driver
import json

###############################
###      AWS FUNCTIONS     ###
###############################

import aws

###############################
###     HELPER FUNCTIONS    ###
###############################

# get all the local files created
def get_local_job_files(folder):
  try:
    files = [f for f in listdir(folder) if isfile(join(folder, f))]
    return files
  except:
    print("There was an error getting all the files.")

# get log file
def get_key_log_file(prefix, files):
  for file in files:
    key = prefix + file
    if key.endswith('.count.log'):
      return key

# get result file
def get_key_result_file(prefix, files):
  for file in files:
    key = prefix + file
    if key.endswith('.annot.vcf'):
      return key

# check user role associated with this annotation request
def is_free_user(annotation_details):
  user_role = annotation_details['user_role']
  return user_role == 'free_user'

# clean up local files
def delete_local_job_files(folder):
  try:
    shutil.rmtree(folder)
  except:
    print("There was an error deleting the local files.")

###############################
###          TIMER          ###
###############################

# rudimentary timer for coarse-grained profiling
class Timer(object):
  def __init__(self, verbose=True):
    self.verbose = verbose

  def __enter__(self):
    self.start = time.time()
    return self

  def __exit__(self, *args):
    self.end = time.time()
    self.secs = self.end - self.start
    if self.verbose:
      print("Total runtime: {0:.6f} seconds".format(self.secs))

###############################
###        ANNOTATOR        ###
###############################

if __name__ == '__main__':
  # Call the AnnTools pipeline
  if len(sys.argv) > 1:
    with Timer():

      # get the args: file, folder, key prefix, upload bucket
      file_path = sys.argv[1]
      job_id = sys.argv[2]
      folder = sys.argv[3]
      prefix = sys.argv[4]
      bucket = sys.argv[5]

      # make sure args were passed correctly
      if file_path is None or job_id is None or folder is None or prefix is None or bucket is None:
        print("Check args passed: file path, folder, prefix, bucket.")

      # connect to the database
      table_name = aws.DYNAMODB_ANNOTATIONS_TABLE
      table = aws.get_table(table_name)

      # claim job: returns true if can update status from PENDING to RUNNING
      if aws.claim_annotation_job(table, job_id):

        # run the job
        driver.run(file_path, 'vcf')

        # record complete time
        complete_time = int(time.time())

        # get the local files created from the job
        files = get_local_job_files(folder)

        # connect to s3
        s3 = aws.get_s3()

        # upload files
        aws.upload_files_to_s3(s3, bucket, prefix, folder, files)

        # update annotations database
        key_result_file = get_key_result_file(prefix, files)
        key_log_file = get_key_log_file(prefix, files)
        job_status = 'COMPLETE'
        result_file_location = 'S3'
        aws.set_completed_job_details(table, job_id, bucket, key_result_file, key_log_file, complete_time, job_status, result_file_location)

        # get SNS service
        sns = aws.get_sns()

        # publish message to SNS job results topic
        job_results_topic = aws.SNS_JOB_RESULTS_TOPIC
        aws.publish_message(sns, job_results_topic, job_id)

        # if free user: publish to SNS archive requests topic
        annotation_details = aws.get_annotation_details(table, job_id)
        if is_free_user(annotation_details):
          archive_requests_topic = aws.SNS_ARCHIVE_REQUESTS_TOPIC
          aws.publish_message(sns, archive_requests_topic, job_id)

        # clean up local job files
        delete_local_job_files(folder)

        # print status to console
        print("Annotation run complete. S3 and DynamoDB updated for job id: " + str(job_id))

  else:
    print("A valid .vcf file must be provided as input to this program.")
