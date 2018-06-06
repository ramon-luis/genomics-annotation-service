# Genomics Annotation Service

Genomics Annotation Service is a web application that provides a  genomic annotation service to users.

Users can:
* upload a .vcf file to be annotated
* view all a history of annotation jobs requested by user
* view details of a specific annotation job
* download the results file of a specific annotation job
* view the log file (in-browser) for a specific annotatio job

<kbd>
  <img src="https://github.com/ramon-luis/genomics-annotation-service/raw/master/demo/genomics-annotation-service-screenshot-1.png">
</kbd>
<br />
<kbd>
  <img src="https://github.com/ramon-luis/genomics-annotation-service/raw/master/demo/genomics-annotation-service-screenshot-2.png">
</kbd>
<br />
<kbd>
  <img src="https://github.com/ramon-luis/genomics-annotation-service/raw/master/demo/genomics-annotation-service-screenshot-5.png">
</kbd>

## Application Architecture

The application front-end is built with Python/Flask. The back-end is hosted on Amazon Web Services (AWS) and uses the below AWS services:
* ec2 (Elastic Compute Cloud) - resizable computing capacity
* DynamoDB - nonrelational database
* S3 (Simple Storage Service) - flat object storage
* Glacier - long-term, durable object storage
* SQS (Simple Queue Service) - message queue
* SNS (Simple Notification Service) - publish/subscribe message notifications
* SES (Simple Email Service) - email sending
* ELB (Elastic Load Balancin) - load balancing
* Cloudwatch - monitoring and alarm service

**Front-end Implementation**
* ec2 instances running a Flask web server host the user web interface
* Front-end instances are part of a load balancer that:
  * directs traffic accrodingly between available instances
  * scales-in/scales-out by adding/removing ec2 instances running the web server based on incoming traffic triggers

**Back-end Implementation**
* Annotation job requests are run on separate ec2 instances with message queues used to manage communication.
* Annotation ec2 instances will scale-in/scale-out (i.e. add/remove instances) based on the number of pending jobs requested in the message queue.
* Seperate utility ec2 instances exist to handle supplemental services:
  * a notification instance sends an email to users when an annotation job has completed
  * an archival instance archives job results files (from S3 to Glacier) if a user is a free user and the time to archive has expired
  * a thaw instance requests that archived files be made accesible (moved from Glacier to staging area) when a user upgrades to premium
  * a restore instance actually makes files accessible (restoring files from staging area to S3) once they have thawed
* Messages queues (SQS) and topics (SNS) are used to manage communication between front-end, back-end, and utility services

<kbd>
  <img src="https://github.com/ramon-luis/genomics-annotation-service/raw/master/demo/genomics-annotation-service-architecture.png">
</kbd>

### File Structure
* `anntools/`:
  * `annotator.py`: listens for messages in the ramonlrodriguez_job_reqests AWS SQS message queue. Messages are sent to this queue by the web application when an annotation job is requested by a user. The user input file is taken from S3 and used by `run.py` to run the annotation locally on the ec2 annotation instance.
  * `aws.py`: contains AWS functions and constants that are used by annotation files
  * `config.ini`: contains centralized configuration settings for AWS and other global variables
  * `data/`: directory where annotation data is stored locally before being uploaded to AWS
  * `run.py`: contains logic to run the annotation job locally. Once the job is complete, details are published to AWS DynamoDB and results files are uploaded to AWS S3. Additionally, a message is published to the AWS SNS topic ramonlrodriguez_job_results in order for users to be notified that the annotation job is complete. If the user was a 'free_user' at the time of the annotation request, then a message is published to the AWS SNS topic ramonlrodriguez_archive_requests in order for the job to be archived once sufficient time has elapsed. After all information has been uploaded to AWS, any local files are deleted from the ec2 instance.
  * other support files associated with the annotation process
* `gas/`:
  * `views.py`: contains core logic for the Flask web app and routes for the annotations web server.
    * `/`: home
    * `/login`: login using Globus identity management
    * `/annotate`: upload a file to request an annotation
    * `/annotate/job`: start the annotation process for uploaded file
    * `/annotations`: list all annotations for user
    * `/annotation_details/<job_id>`: list details of a specific annotation, including link to download results file from annotation
    * `/annotation_details/<job_id>/log`: show the log file associated with a specific annotation
    * `/subscribe`: upgrade user role to premium using Stripe to process credit card subscription payment
    * `/free_user`: revert user role to 'free_user' (helper route for testing)
  * `templates/`: contains html templates for the Flask web app
  * other support files associated with the web application
* `load_testing/`:
  * `annotator_load_testing.py`: contains python script that blasts messages to AWS SNS topic ramonlrodriguez_job_requests_queue in order to test AWS CloudWatch alarms that add/remove ec2 instances running the annotator based on the number of messages sent to the job requests queue. Messages are filled with dummy data, which means the annotator and the utility (listener) files should NOT be running since the intent is only to fill the message queue, not to actually process annotation jobs.
  * `aws.py`: contains AWS functions and constants that are used by `annotator_load_testing.py`.
  * `config.ini`: contains centralized configuration settings for AWS and other global variables.
  * `screenshots/`: contains screenshots from load testing
  * `web_load_testing.py`: contains locust script that send requests to various web resources associated with the annotation web server in order to test the AWS CloudWatch alarms that add/remove ec2 intances running the web server based on the number of successful 200 HTTP codes processed.
* `user_data/`:
  * `auto_scaling_user_data_annotator.txt`: contains user data to setup annotators that are created from AWS Launch Configuration ramonlrodriguez-launch-config-annotator.
  * `auto_scaling_user_data_web_server.txt`: contains user data to setup annotators that are created from AWS Launch Configuration ramonlrodriguez-launch-config-web.
* `util/`:
  * `archive_listen.py`: listens for messages in the ramonlrodriguez_archive_requests AWS SQS message queue. Messages are sent to this queue if a job completes that was requested when a user role was 'free_user'. When a message is received, the time that the job was completed is compared to the time when jobs should be archived. If sufficient time has elapsed, then the user role associated with the job is checked to make sure that the user is still a 'free_user' since it is possible that the user have have upgraded their account during the wait-to-archive time. If the user is still a free_user, then the results file for the job associated with the message is archived to AWS Glacier and the results file in S3 is deleted.  The DynamoDB record for the job is updated to note that the results file is stored in Glacier, and the associated Glacier archive id is added to the record.
  * `aws.py`: contains AWS functions and constants that are used by utility files.
  * `config.ini`: contains centralized configuration settings for AWS and other global variables that are used by utility files.
  * `notify_listen.py`: listens for messages in the ramonlrodriguez_job_results AWS SQS message queue. Messages are sent to this queue when a job completes. When a message is recieved, an email is composed and sent to the user using AWS SES in order to notify the user that the annotation job has completed.
  * `restore_listen.py`: listens for messages in the ramonlrodriguez_restore_results AWS SQS message queue. Messages are sent to this queue by AWS Glacier when files that were previously archived in Glacier are available to be accessed.  When a message is received, the previously archived file is moved to S3 and the record associated with the job in DynamoDB is updated to reflect where the file is stored.
  * `thaw_listen.py`: listens for messages in the ramonlrodriguez_thaw_requests AWS SQS message queue. Messages are sent to this queue when a user upgrades his or her user role from 'free_user' to 'premium_user'.  When a message is received, each annotation job in the DynamoDB that is associated with the user is evaluated to check the location of the results file. If the results file is currently stored in AWS Glacier, then a request is made to restore the file. The request is made so that a message is sent to the AWS SNS topic ramonlrodriguez_restore_results when the file is available so that it may then be moved to S3.
* `zip_files/`:
  * `gas_annotator.zip` contains annotator files that are loaded onto annotator instances from ramonlrodriguez-auto-scaler-annotator
  * `gas_web_server.zip` contains web server files that are loaded onto web instances from ramonlrodriguez-auto-scaler-web

## Built With

* [Amazon Web Services](https://aws.amazon.com/) - back-end services
* [Flask](http://flask.pocoo.org/) - web server
* [Bootstrap](https://getbootstrap.com/) - styling
* [Python](https://www.python.org/)

## Author

* [**Ramon-Luis**](https://github.com/ramon-luis)
