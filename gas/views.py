# views.py
# Application logic for the GAS

import uuid
import time
import json
import requests
from datetime import datetime

import boto3
from botocore.client import Config
from boto3.dynamodb.conditions import Key

from flask import (abort, flash, redirect, render_template,
  request, session, url_for)

from gas import app, db
from decorators import authenticated, is_premium
from auth import get_profile, update_profile

import stripe

###############################
###       HOME & LOGIN      ###
###############################

# Home page
@app.route('/', methods=['GET'])
def home():
  return render_template('home.html')

# Login page; send user to Globus Auth
@app.route('/login', methods=['GET'])
def login():
  app.logger.info('Login attempted from IP {0}'.format(request.remote_addr))
  # If user requested a specific page, save it to session for redirect after authentication
  if (request.args.get('next')):
    session['next'] = request.args.get('next')
  return redirect(url_for('authcallback'))

###############################
###    ANNOTATION ROUTES    ###
###############################

# Request an annotation
@app.route('/annotate', methods=['GET'])
@authenticated
def annotate():
  # connect to s3 - use v4 signature
  try:
    s3 = boto3.client('s3',
      region_name=app.config['AWS_REGION_NAME'],
      config=Config(signature_version='s3v4')
    )
  except Exception as e:
    print("There was error connecting to S3: \n" + str(e))
    return abort(500)

  # create params for policy
  bucket = app.config['AWS_S3_INPUTS_BUCKET']
  user_id = session['primary_identity']
  # generate unique key - required to store in S3 flat namespace
  key = app.config['AWS_S3_KEY_PREFIX'] + '/' + user_id + '/' + str(uuid.uuid4()) + '/' + '${filename}'
  # Redirect to a route that will call the annotator
  redirect_url = str(request.url) + "/job"
  encryption = app.config['AWS_S3_ENCRYPTION']
  acl = app.config['AWS_S3_ACL']
  expires_in = app.config['AWS_SIGNED_REQUEST_EXPIRATION']
  fields = {
    "success_action_redirect": redirect_url,
    "x-amz-server-side-encryption": encryption,
    "acl": acl
  }

  conditions = [
      ["starts-with", "$success_action_redirect", redirect_url],
      {"x-amz-server-side-encryption": encryption},
      {"acl": acl}
  ]

  # set conditions based on type of user: non-premium users have limit to file size
  # https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-HTTPPOSTConstructPolicy.html#sigv4-PolicyConditions
  # http://boto3.readthedocs.io/en/latest/reference/services/s3.html#S3.Client.generate_presigned_post
  # is_premium_user = (session['role'] == 'premium_user')
  # if is_premium_user:
  #   conditions = [
  #     ["starts-with", "$success_action_redirect", redirect_url],
  #     {"x-amz-server-side-encryption": encryption},
  #     {"acl": acl}
  #   ]
  # else:
  #   conditions = [
  #     ["starts-with", "$success_action_redirect", redirect_url],
  #     {"x-amz-server-side-encryption": encryption},
  #     {"acl": acl},
  #     ["content-length-range", 0, 15]
  #   ]

  # generate presigned post with policy
  try:
    presigned_post = s3.generate_presigned_post(
        Bucket=bucket,
        Key=key,
        Fields=fields,
        Conditions=conditions,
        ExpiresIn=expires_in
    )
  except Exception as e:
    print("There was error generating a presigned post: \n" + str(e))
    return abort(500)

  # render the upload form template
  return render_template('annotate.html', s3_post=presigned_post)

# Fires off an annotation job
@app.route('/annotate/job', methods=['GET'])
@authenticated
def create_annotation_job_request():
  # get url params
  bucket = request.args.get('bucket')
  key = request.args.get('key')
  if bucket is None or key is None:
    return "400 Bad Request. This service requires a valid AWS bucket and file."

  # define data fields
  job_id = extract_job_id(key)
  input_file_name = extract_filename(key)
  user_id = extract_user_id(key)
  user_profile = get_profile(identity_id=user_id)
  user_name = user_profile.name
  user_email = user_profile.email
  user_role = user_profile.role
  current_time = int(time.time())
  job_status = 'PENDING'

  # create data hash
  data = {'job_id': job_id,
          'user_id': user_id,
          'user_name': user_name,
          'user_email': user_email,
          'user_role': user_role,
          'input_file_name': input_file_name,
          's3_inputs_bucket': bucket,
          's3_key_input_file': key,
          'submit_time': current_time,
          'job_status': job_status
  }

  # connect to DynamoDB
  try:
    dynamodb = boto3.resource('dynamodb',
      region_name=app.config['AWS_REGION_NAME']
    )
    table = dynamodb.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])
  except Exception as e:
    print("There was error connecting to dynamodb: \n" + str(e))
    return abort(500)

  # store data in AWS DynamoDB
  try:
    table.put_item(Item=data)
  except Exception as e:
    print("There was error putting the item in dynamodb: \n" + str(e))
    return abort(500)

  # connect to SNS
  try:
    sns = boto3.client('sns', region_name=app.config['AWS_REGION_NAME'])
  except Exception as e:
    print("There was error connecting to SNS: \n" + str(e))
    return abort(500)

  # publish data to SNS
  try:
    topic_arn = app.config['AWS_SNS_JOB_REQUEST_TOPIC']
    message = json.dumps(data)
    sns_response = sns.publish(
      TopicArn=topic_arn,
      Message=message
    )
  except Exception as e:
    print("There was error publishing a message to SNS: \n" + str(e))
    return abort(500)

  # confirm success to user
  return render_template('annotate_confirm.html', job_id=job_id)

# List all annotations for the user
@app.route('/annotations', methods=['GET'])
@authenticated
def annotations_list():
  # get user id from session
  user_id = session['primary_identity']

  # connect to DynamoDB
  try:
    dynamodb = boto3.resource('dynamodb',
      region_name=app.config['AWS_REGION_NAME']
    )
    table = dynamodb.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])
  except Exception as e:
    print("There was error connecting to dynamodb: \n" + str(e))
    return abort(500)

  # Get list of annotations to display
  # https://stackoverflow.com/questions/35758924/how-do-we-query-on-a-secondary-index-of-dynamodb-using-boto3
  try:
    response = table.query(
      IndexName='user_id_index',
      KeyConditionExpression=Key('user_id').eq(user_id)
    )
    annotations = response['Items']
  except Exception as e:
    print("There was error querying dynamodb: \n" + str(e))
    return abort(500)

  return render_template('annotations.html', annotations=annotations, time=time)

# Display details of a specific annotation job
@app.route('/annotations/<job_id>', methods=['GET'])
@authenticated
def annotation_details(job_id):
  # get user id from session
  user_id = session['primary_identity']
  user_profile = get_profile(identity_id=user_id)
  user_role = user_profile.role

  # connect to DynamoDB
  try:
    dynamodb = boto3.resource('dynamodb', region_name=app.config['AWS_REGION_NAME'])
    table = dynamodb.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])
  except Exception as e:
    print("There was error connecting to dynamodb: \n" + str(e))
    return abort(500)

  # Get the annotation details
  # http://boto3.readthedocs.io/en/latest/guide/dynamodb.html
  try:
    response = table.get_item(
      Key={ 'job_id': job_id
      }
    )
    annotation_details = response['Item']
  except Exception as e:
    print("There was error getting item from dynamodb: \n" + str(e))
    return abort(500)

  # confirm that the requested annotation belongs to this user
  annotation_user_id = annotation_details['user_id']
  if annotation_user_id != user_id:
    return "You are not authorized to view this job."

  # connect to s3 - use v4 signature
  try:
    s3 = boto3.client('s3',
      region_name=app.config['AWS_REGION_NAME'],
      config=Config(signature_version='s3v4')
    )
  except Exception as e:
    print("There was error connecting to S3: \n" + str(e))
    return abort(500)

  # generate a presigned url to download the input file
  # http://boto3.readthedocs.io/en/latest/guide/s3.html
  try:
    input_file_bucket = annotation_details['s3_inputs_bucket']
    input_file_key = annotation_details['s3_key_input_file']
    input_file_presigned_download_url = s3.generate_presigned_url(
      ClientMethod='get_object',
      Params={
          'Bucket': input_file_bucket,
          'Key': input_file_key
      }
    )
  except Exception as e:
    print("There was error generating a presigned url for the input file: \n" + str(e))
    return abort(500)

  # if job complete, then generate a presigned url to download results
  if annotation_details['job_status'] == 'COMPLETE':
    try:
      result_file_bucket = annotation_details['s3_results_bucket']
      result_file_key = annotation_details['s3_key_result_file']
      result_file_presigned_download_url = s3.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': result_file_bucket,
            'Key': result_file_key
        }
      )
    except Exception as e:
      print("There was error generating a presigned url for the results file: \n" + str(e))
      return abort(500)
  else:
    result_file_presigned_download_url = None

  return render_template( 'annotation_details.html',
                          user_role=user_role,
                          annotation_details=annotation_details,
                          time=time,
                          input_file_presigned_download_url=input_file_presigned_download_url,
                          result_file_presigned_download_url=result_file_presigned_download_url
  )

# Display the log file for an annotation job
@app.route('/annotations/<job_id>/log', methods=['GET'])
@authenticated
def annotation_log(job_id):
  # get user id from session
  user_id = session['primary_identity']

  # connect to DynamoDB
  try:
    dynamodb = boto3.resource('dynamodb',
      region_name=app.config['AWS_REGION_NAME']
    )
    table = dynamodb.Table(app.config['AWS_DYNAMODB_ANNOTATIONS_TABLE'])
  except Exception as e:
    print("There was error connecting to dynamodb: \n" + str(e))
    return abort(500)

  # Get the job details from db
  try:
    response = table.get_item(
      Key={ 'job_id': job_id
      }
    )
    annotation_details = response['Item']
  except Exception as e:
    print("There was error getting an item from dynamodb: \n" + str(e))
    return abort(500)

  # confirm that the requested annotation belongs to this user
  log_file_user_id = annotation_details['user_id']
  if log_file_user_id != user_id:
    return "You are not authorized to view the log file for this job."

  # connect to s3 - use v4 signature
  try:
    s3 = boto3.resource('s3',
      region_name=app.config['AWS_REGION_NAME'],
      config=Config(signature_version='s3v4')
    )
  except Exception as e:
    print("There was error connecting to S3: \n" + str(e))
    return abort(500)

  # get the log file
  # https://stackoverflow.com/questions/31976273/open-s3-object-as-a-string-with-boto3
  log_file_bucket = annotation_details['s3_results_bucket']
  log_file_key = annotation_details['s3_key_log_file']
  raw_log_file = s3.Object(log_file_bucket, log_file_key)
  log_file = raw_log_file.get()['Body'].read().decode('utf-8')

  return render_template('annotation_log_file.html',
    annotation_details=annotation_details,
    time=time,
    log_file=log_file
  )

###############################
###       SUBSCRIPTION      ###
###############################

# Subscription management handler
@app.route('/subscribe', methods=['GET', 'POST'])
@authenticated
def subscribe():
  if request.method == 'GET':
    # show subscription form
    return render_template('subscribe.html')

  # https://stripe.com/docs/checkout/flask
  if request.method == 'POST':
    # set stripe api key
    stripe.api_key = app.config['STRIPE_SECRET_KEY']

    # get stripe token
    stripe_token = request.form['stripe_token']

    # get user email
    user_id = session['primary_identity']
    user_profile = get_profile(identity_id=user_id)
    user_email = user_profile.email

    # create new customer in Stripe
    customer = stripe.Customer.create(
      email=user_email,
      source=stripe_token
    )

    # subscribe the customer
    subscription = stripe.Subscription.create(
      customer=customer.id,
      items=[{'plan': 'premium_plan'}],
    )

    # update user role in Globus
    update_profile(
      identity_id=session['primary_identity'],
      role='premium_user'
    )

    # connect to SNS
    try:
      sns = boto3.client('sns', region_name=app.config['AWS_REGION_NAME'])
    except Exception as e:
      print("There was error connecting to SNS: \n" + str(e))
      return abort(500)

    # publish user id to SNS to request thaw for any archived files
    try:
      topic_arn = app.config['AWS_SNS_THAW_REQUESTS_TOPIC']
      message = json.dumps(user_id)
      sns_response = sns.publish(
        TopicArn=topic_arn,
        Message=message
      )
    except Exception as e:
      print("There was error publishing a message to SNS: \n" + str(e))
      return abort(500)

    # show subcription confirmation
    return render_template('subscribe_confirm.html', stripe_id=customer.id)

# Convert current user back to free  - used for faster testing
@app.route('/free_user', methods=['GET'])
@authenticated
def free_user():
  update_profile(
      identity_id=session['primary_identity'],
      role='free_user'
    )
  return "User role has been updated to: free_user."

###############################
###      ERROR HANDLING     ###
###############################

# 404 error handler
@app.errorhandler(404)
def page_not_found(e):
  return render_template('error.html',
    title='Page not found', alert_level='warning',
    message="The page you tried to reach does not exist. Please check the URL and try again."), 404

# 403 error handler
@app.errorhandler(403)
def forbidden(e):
  return render_template('error.html',
    title='Not authorized', alert_level='danger',
    message="You are not authorized to access this page. If you think you deserve to be granted access, please contact the supreme leader of the mutating genome revolutionary party."), 403

# 405 error handler
@app.errorhandler(405)
def not_allowed(e):
  return render_template('error.html',
    title='Not allowed', alert_level='warning',
    message="You attempted an operation that's not allowed; get your act together, hacker!"), 405

# 500 error handler
@app.errorhandler(500)
def internal_error(error):
  return render_template('error.html',
    title='Server error', alert_level='danger',
    message="The server encountered an error and could not process your request."), 500

###############################
###     HELPER FUNCTIONS    ###
###############################

# helper function to get filename from key
def extract_filename(key):
  filename = key[key.rfind('/')+1:]
  return filename

# helper function to get user id from key
def extract_user_id(key):
  user_job_id_filename = key[key.find('/')+1:]
  user_id = user_job_id_filename[:user_job_id_filename.find('/')]
  return user_id

# helper function to get job id from key
def extract_job_id(key):
  user_job_id_filename = key[key.find('/')+1:]
  job_id_filename = user_job_id_filename[user_job_id_filename.find('/')+1:]
  job_id = job_id_filename[:job_id_filename.rfind('/')]
  return job_id

# helper function to get prefix from key
def extract_prefix(key):
  cnet_user_job_id = key[:key.rfind('/')+1]
  return cnet_user_job_id
