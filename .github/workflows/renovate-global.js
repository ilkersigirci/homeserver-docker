const config = {
  // This workflow is intended to run against the current repository only.
  onboarding: false,
  requireConfig: "required",
  branchPrefix: "renovate-gha/",
};

if (process.env.GITHUB_REPOSITORY) {
  config.repositories = [process.env.GITHUB_REPOSITORY];
}

module.exports = config;
