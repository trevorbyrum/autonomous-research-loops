variable "GEN2_DATA_ROOT" {}

group "default" {
  targets = ["runner", "engine", "gateway", "fixture"]
}
target "images" {
  matrix = {
    role = ["runner", "engine", "gateway", "fixture"]
  }
  name = role
  context = "."
  contexts = {
    approved-inputs = "${GEN2_DATA_ROOT}/storage/build-inputs"
  }
  dockerfile = "deploy/gen2/live/Dockerfile"
  target = role
  platforms = ["linux/amd64"]
  network = "none"
  tags = ["gen2-2e1-${role}:offline"]
  output = ["type=docker"]
  pull = false
}

target "cli-contract" {
  dockerfile-inline = "FROM scratch"
  context = "."
  network = "none"
  pull = false
  platforms = ["linux/amd64"]
  output = ["type=cacheonly"]
}
