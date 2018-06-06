import time


###############################
###      AWS FUNCTIONS     ###
###############################

import aws

###############################
###    Publish Messages     ###
###############################

def publish_messages(count_of_messages_to_send):
  # connect to SNS
  sns = aws.get_sns()

  # set the topic to Job Request where scale-out alarm sits
  topic = aws.SNS_JOB_REQUESTS_TOPIC

  # the message doesn't matter:
  # job listener is not running during testing,
  # so message will not be picked up for processing
  message_data = {'job_id': 'job_for_test_msg',
          'user_id': 'user_for_test_msg',
          'user_name': 'john doe',
          'user_email': 'johndoe@example.com',
          'user_role': 'free_user',
          'input_file_name': 'test.vcf',
          's3_inputs_bucket': aws.S3_INPUTS_BUCKET,
          's3_key_input_file': 'ramonlrodriguez/annotator_testing/test.vcf',
          'submit_time': int(time.time()),
          'job_status': 'TEST_JOB'
  }

  # publish the messages
  for message in range(count_of_messages_to_send):
    aws.publish_message(sns, topic, message_data)

###############################
###   Send Test Messages    ###
###############################

messages_per_blast = 5
seconds_between_blasts = 1

print("-----------------------")
print("Blasting messages until program stopped:")
print("ctrl+c to stop\n")

print("-----------------------")
print("Messages per blast: " + str(messages_per_blast))
print("Seconds between blasts: " + str(seconds_between_blasts))
print("-----------------------\n\n")

while True:
  print("-----------------------")
  print("\nBlasting messages...")
  publish_messages(messages_per_blast)
  print("\nSleeping...")
  time.sleep(seconds_between_blasts)
