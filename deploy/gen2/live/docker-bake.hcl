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
    approved-inputs = "/home/trevor/.local/share/gen2-2e1/storage/build-inputs"
  }
  dockerfile = "deploy/gen2/live/Dockerfile"
  target = role
  platforms = ["linux/amd64"]
  tags = ["gen2-2e1-${role}:offline"]
  output = ["type=docker"]
  pull = false
}
