from locust import HttpLocust, TaskSet, task

class UserBehavior(TaskSet):
  def on_start(self):
    """ on_start is called when a Locust start before any task is scheduled """

  # Login was called so profile, annotations, and annotate could be accessed.
  # It was later deleted since instance had my credentials.

  @task(5)
  def index(self):
    self.client.get("/")

  @task(4)
  def profile(self):
    self.client.get("/profile")

  @task(3)
  def annotations(self):
    self.client.get("/annotations")

  @task(2)
  def annotate(self):
    self.client.get("/annotate")

  # to make sure bad route would be recognized as such :)
  @task(1)
  def bad_route(self):
    self.client.get("/bad_route")

class WebsiteUser(HttpLocust):
  task_set = UserBehavior
  min_wait = 1000
  max_wait = 20000
