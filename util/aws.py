import boto3
import botocore
from boto3.dynamodb.conditions import Key, Attr
from botocore.client import Config
from botocore.exceptions import ClientError
import json

import configparser

###############################
###         Config          ###
###############################

config = configparser.ConfigParser()
config.sections()
config.read('config.ini')

###############################
###        Constants        ###
###############################

# Region
REGION_NAME = config['AWS']['REGION_NAME']

# S3
S3_INPUTS_BUCKET = config['AWS']['S3_INPUTS_BUCKET']
S3_RESULTS_BUCKET = config['AWS']['S3_RESULTS_BUCKET']
S3_ACL = config['AWS']['S3_ACL']

# DynamoDB
DYNAMODB_ANNOTATIONS_TABLE = config['AWS']['DYNAMODB_ANNOTATIONS_TABLE']

# Glacier
GLACIER_VAULT = config['AWS']['GLACIER_VAULT']
GLACIER_ACCOUNT_ID = config['AWS']['GLACIER_ACCOUNT_ID']

# SQS
SQS_JOB_REQUESTS_QUEUE = config['AWS']['SQS_JOB_REQUESTS_QUEUE']
SQS_JOB_RESULTS_QUEUE = config['AWS']['SQS_JOB_RESULTS_QUEUE']
SQS_ARCHIVE_REQUESTS_QUEUE = config['AWS']['SQS_ARCHIVE_REQUESTS_QUEUE']
SQS_THAW_REQUESTS_QUEUE = config['AWS']['SQS_THAW_REQUESTS_QUEUE']
SQS_RESTORE_RESULTS_QUEUE = config['AWS']['SQS_RESTORE_RESULTS_QUEUE']

# SNS
SNS_JOB_REQUESTS_TOPIC = config['AWS']['SNS_JOB_REQUESTS_TOPIC']
SNS_JOB_RESULTS_TOPIC = config['AWS']['SNS_JOB_RESULTS_TOPIC']
SNS_ARCHIVE_REQUESTS_TOPIC = config['AWS']['SNS_ARCHIVE_REQUESTS_TOPIC']
SNS_THAW_REQUESTS_TOPIC = config['AWS']['SNS_THAW_REQUESTS_TOPIC']
SNS_RESTORE_RESULTS_TOPIC = config['AWS']['SNS_RESTORE_RESULTS_TOPIC']

# Email (SES)
MAIL_DEFAULT_SENDER = config['AWS']['MAIL_DEFAULT_SENDER']

# Archive
FREE_USER_DATA_RETENTION = config['ARCHIVE']['FREE_USER_DATA_RETENTION'] # time before free user results are archived (in seconds)

###############################
###            S3           ###
###############################

# get an s3 connection
def get_s3():
  try:
    s3 = boto3.resource('s3')
  except Exception as e:
    print("There was an error connecting to S3:\n" + str(e))
  return s3

# download file from s3
def download_file_from_s3(s3, bucket, key, file_path):
  try:
    s3.Bucket(bucket).download_file(key, file_path)
  except botocore.exceptions.ClientError as e:
    if e.response['Error']['Code'] == "404":
      print("The requested file could not be found in S3 for processing.")
    else:
      print("There was an error downloading the file for processing:\n" + str(e))

# upload files to s3
def upload_files_to_s3(s3, bucket, prefix, local_folder, local_files):
  for file in local_files:
    # define file path and AWS key
    file_path = local_folder + file
    key = prefix + file
    # upload
    try:
      s3.meta.client.upload_file(file_path, bucket, key)
    except:
      print("There was an error uploading the file: " + str(key))

# put data in S3
def put_data_in_S3(s3, bucket, key, data):
  object = s3.Object(bucket, key)
  object.put(Body=data.read())
  print("File placed in S3.")

# delete s3 file
def delete_s3_file(s3, bucket, key):
  s3_object = s3.Object(bucket, key)
  s3_object.delete()

###############################
###        DynamoDB         ###
###############################

# get table by name
def get_table(table_name):
  try:
    aws_db = boto3.resource('dynamodb', region_name=REGION_NAME)
    table = aws_db.Table(table_name)
    return table
  except Exception as e:
    print("There was an error coneecting to the annotations database:\n" + str(e))

# get annotations for a user from annotations db
def get_annotations(table, user_id):
  try:
    response = table.query(
      IndexName='user_id_index',
      KeyConditionExpression=Key('user_id').eq(user_id)
    )
    annotations = response['Items']
    return annotations
  except Exception as e:
    print("There was an error getting the annotations for user from the annotations database:\n" + str(e))

# get details from table by job id
def get_annotation_details(table, job_id):
  try:
    response = table.get_item(
      Key={ 'job_id': job_id
      }
    )
    annotation_details = response['Item']
    return annotation_details
  except Exception as e:
    print("There was an error getting the annotation details from the annotations database:\n" + str(e))

# claim PENDING job: returns True if job status can be updated from PENDING to RUNNING
# https://stackoverflow.com/questions/37053595/how-do-i-conditionally-insert-an-item-into-a-dynamodb-table-using-boto3?utm_medium=organic&utm_source=google_rich_qa&utm_campaign=google_rich_qa
# http://boto3.readthedocs.io/en/latest/reference/services/dynamodb.html#DynamoDB.Table.update_item
def claim_annotation_job(table, job_id):
  try:
    response = table.update_item(
      Key={'job_id': job_id},
      UpdateExpression="set job_status=:job_status",
      ConditionExpression=Attr('job_status').eq('PENDING'),
      ReturnValues='UPDATED_NEW',
      ExpressionAttributeValues={
        ':job_status' : 'RUNNING'
      }
    )
    return response['Attributes']['job_status'] == 'RUNNING'
  except botocore.exceptions.ClientError as e:
    # Ignore the ConditionalCheckFailedException, bubble up other exceptions.
    if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
      print("There was an error updating the job status in the annotations database.")
    else:
      print("Job not PENDING.")
      return False

# set field for a completed job in the annotations database
def set_completed_job_details(table, job_id, bucket, key_result_file,
  key_log_file, complete_time, status, result_file_location):
  try:
    table.update_item(
      Key={'job_id': job_id},
      UpdateExpression="set s3_results_bucket=:results_bucket, "
                        "s3_key_result_file=:result_file, "
                        "s3_key_log_file=:log_file, "
                        "complete_time=:complete_time, "
                        "job_status=:job_status, "
                        "result_file_location=:result_file_location",
      ExpressionAttributeValues={
        ':results_bucket' : bucket,
        ':result_file' : key_result_file,
        ':log_file' : key_log_file,
        ':complete_time' : complete_time,
        ':job_status' : status,
        ':result_file_location': result_file_location
      }
    )
  except:
    print("There was an error updating the job database for job id: " + str(job_id))

# claim archive job
def claim_archive_job(table, job_id):
  try:
    response = table.update_item(
      Key={'job_id': job_id},
      UpdateExpression="set result_file_location=:result_file_location",
      ConditionExpression=Attr('result_file_location').eq('S3'),
      ReturnValues='UPDATED_NEW',
      ExpressionAttributeValues={
        ':result_file_location' : 'archiving...'
      }
    )
    return response['Attributes']['result_file_location'] == 'archiving...'
  except botocore.exceptions.ClientError as e:
    # Ignore the ConditionalCheckFailedException, bubble up other exceptions.
    if e.response['Error']['Code'] != 'ConditionalCheckFailedException':
      print("There was an error updating the result file location in the annotations database.")
    else:
      print("Unable to claim archive job.  It is possible that result file is not located in S3.")
      return False

# set user role in annotations db given job id
def set_user_role(table, job_id, user_role):
  try:
    table.update_item(
      Key={'job_id': job_id},
      UpdateExpression="set user_role=:user_role",
      ExpressionAttributeValues={
        ':user_role': user_role
      }
    )
  except Exception as e:
    print("There was an error setting the user role in the annotations database for job id: " + str(job_id))
    print(str(e))

# update result file location in annotations database
def set_result_file_location(table, job_id, result_file_location):
  try:
    table.update_item(
      Key={'job_id': job_id},
      UpdateExpression="set result_file_location=:result_file_location",
      ExpressionAttributeValues={
        ':result_file_location': result_file_location
      }
    )
    print("Updated result file location in annotations db for job: " + str(job_id))
  except Exception as e:
    print("There was an error updating the result file location in the annotations database for job id: " + str(job_id))
    print(str(e))

# update archive id in annotations database
def set_archive_id(table, job_id, archive_id):
  try:
    table.update_item(
      Key={'job_id': job_id},
      UpdateExpression="set results_file_archive_id=:archive_id",
      ExpressionAttributeValues={
        ':archive_id': archive_id
      }
    )
    print("Updated archive id in annotations db for job: " + str(job_id))
  except Exception as e:
    print("There was an error updating the archive id in the annotations database for job id: " + str(job_id))
    print(str(e))

###############################
###          SQS            ###
###############################

# get SQS
def get_sqs():
  try:
    sqs = boto3.resource('sqs', region_name=REGION_NAME)
    return sqs
  except Exception as e:
    print("There was an error connecting to sqs:\n" + str(e))

# get queue by name
def get_queue(sqs, queue_name):
  try:
    queue = sqs.get_queue_by_name(
      QueueName=queue_name,
    )
    return queue
  except Exception as e:
    print("There was an error getting the queue by name:\n" + str(e))

###############################
###          SNS            ###
###############################

# get SNS service
def get_sns():
  # connect to SNS
  try:
    region_name = 'us-east-1'
    sns = boto3.client('sns', region_name=REGION_NAME)
    return sns
  except Exception as e:
    print("There was an error connecting to AWS SNS:\n" + str(e))

# publish message to SNS topic
def publish_message(sns, topic, message_data):
  # publish data to SNS
  try:
    message = json.dumps(message_data)
    sns_response = sns.publish(
      TopicArn=topic,
      Message=message
    )
    print("Message published to SNS topic " + str(topic))
  except Exception as e:
    print("There was an error publishing a message to SNS topic " + str(topic))
    print(str(e))

###############################
###          SES            ###
###############################

# get SES connection
def get_ses():
  try:
    ses = boto3.client('ses', region_name=REGION_NAME)
    return ses
  except Exception as e:
    print("There was an error creating a connection to SES:\n" + str(e))

# notify user: send an email
def notify_user(ses, annotation_details):
  # set the email details
  user_email = [annotation_details['user_email']]
  user_name = annotation_details['user_name']
  job_id = annotation_details['job_id']
  input_file_name = annotation_details['input_file_name']
  sender = MAIL_DEFAULT_SENDER
  subject = 'GAS Annotation Request Complete'
  body = ('Hi ' + user_name + ',\n\n' + 'Your requested annotation job is complete.\n\n' +
          'Request ID: ' + job_id +'\n' +
          'Input File: ' + input_file_name + '\n\n' +
          'Annotation details can be viewed at:\n' + 'https://ramonlrodriguez.ucmpcs.org:4433/annotations/' + job_id
  )

  # send the email
  try:
    response = ses.send_email(
      Destination = {'ToAddresses': user_email},
      Message={
        'Body': {'Text': {'Charset': "UTF-8", 'Data': body}},
        'Subject': {'Charset': "UTF-8", 'Data': subject},
      },
      Source=sender)
    print("Notification sent to " + user_name + ' (' + user_email[0] + ') for job id ' + job_id)
    return response['ResponseMetadata']['HTTPStatusCode']
  except Exception as e:
    print("There was an error sending the email with SES:\n" + str(e))

###############################
###        Glacier          ###
###############################

# get Glacier resource
def get_glacier_resource():
  try:
    glacier_resource = boto3.resource('glacier', region_name=REGION_NAME)
    return glacier_resource
  except Exception as e:
    print("There was an error connecting to Glacier:\n" + str(e))

# get vault for a Glacier resource
def get_vault(glacier_resource):
  try:
    vault = glacier_resource.Vault(GLACIER_ACCOUNT_ID, GLACIER_VAULT)
    return vault
  except Exception as e:
    print("There was an error getting the Glacier vault:\n" + str(e))

# archive annotation result file in s3 to glacier vault
def archive_result_file(s3, vault, annotation_details):
  # get s3 object
  s3_key_result_file = annotation_details['s3_key_result_file']
  s3_results_bucket = annotation_details['s3_results_bucket']
  s3_object = s3.Object(s3_results_bucket, s3_key_result_file)

  # set the annotation job id as the archive description
  archive_description = annotation_details['job_id']

  # archive s3 object as it is read
  try:
    archive_object = vault.upload_archive(
      archiveDescription=archive_description,
      body=s3_object.get()['Body'].read()
    )
    print('Archive response: ' + str(archive_object))
    return archive_object.id
  except Exception as e:
    print("There was an error moving result file from S3 to Glacier:\n" + str(e))

# get Glacier client
def get_glacier_client():
  try:
    glacier_client = boto3.client('glacier', region_name=REGION_NAME)
    return glacier_client
  except Exception as e:
    print("There was an error connecting to Glacier:\n" + str(e))

# request archive restore from Glacier client
def request_restore(glacier_client, archive_id, tier):
  try:
    response = glacier_client.initiate_job(
      vaultName=GLACIER_VAULT,
      jobParameters={
        'Type': 'archive-retrieval',
        'ArchiveId': archive_id,
        'SNSTopic': SNS_RESTORE_RESULTS_TOPIC,
        'Tier': tier
      }
    )
    print('Thaw succesfully requested: \n' + str(response))
  except botocore.exceptions.ClientError as e:
    # Handle the InsufficientCapacityException, bubble up other exceptions.
    if e.response['Error']['Code'] == 'InsufficientCapacityException':
      # request restore using Standard processing
      print("There was an error requesting an expedited thaw:\n" + str(e))
      print("Trying again with Standard tier initiate job request.")
      request_restore(glacier_client, archive_id, 'Standard')
    else:
      print("There was an error requesting the file to be restored from Glacier:\n" + str(e))

# get archive data from Glacier client
def get_archive_data(glacier_client, restore_job_id):
  try:
    archive_data = glacier_client.get_job_output(
      vaultName=GLACIER_VAULT,
      jobId=restore_job_id
    )
    return archive_data
  except Exception as e:
    print("There was an error getting the archive data from Glacier:\n" + str(e))
