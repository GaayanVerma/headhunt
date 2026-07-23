"""GraphQL query definitions."""

PROFILE_AND_REPOS_QUERY = """
query CandidateGitHub($login: String!, $cursor: String) {
  rateLimit { remaining resetAt cost }
  user(login: $login) {
    login
    name
    bio
    company
    location
    websiteUrl
    email
    twitterUsername
    followers { totalCount }
    following { totalCount }
    createdAt
    avatarUrl
    isHireable
    organizations(first: 20) { nodes { login } }
    contributionsCollection {
      contributionCalendar { totalContributions }
    }
    repositories(
      first: 50
      after: $cursor
      ownerAffiliations: [OWNER]
      orderBy: {field: PUSHED_AT, direction: DESC}
      isFork: null
    ) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        id
        name
        nameWithOwner
        description
        url
        homepageUrl
        owner { login __typename }
        isFork
        isArchived
        isTemplate
        mirrorUrl
        visibility
        defaultBranchRef {
          name
          target {
            ... on Commit {
              history { totalCount }
            }
          }
        }
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
        repositoryTopics(first: 15) { nodes { topic { name } } }
        licenseInfo { spdxId }
        stargazerCount
        forkCount
        watchers { totalCount }
        issues(states: OPEN) { totalCount }
        diskUsage
        createdAt
        updatedAt
        pushedAt
        releases(first: 1, orderBy: {field: CREATED_AT, direction: DESC}) {
          totalCount
          nodes { tagName createdAt }
        }
        hasIssuesEnabled
        hasProjectsEnabled
        hasWikiEnabled
        hasDiscussionsEnabled
      }
    }
  }
  organization(login: $login) {
    login
  }
}
"""

ORG_CHECK_QUERY = """
query OrgCheck($login: String!) {
  organization(login: $login) { login }
}
"""

# contributionsCollection(from:, to:) only accepts a window up to 1 year - GitHub
# silently clamps a wider range. To approximate multi-year history, this query is
# issued N times with sequential 1-year windows and the results are merged by the
# fetcher. *ByRepository(maxRepositories: 100) is a flat capped list (no pageInfo
# cursor) - more than 100 contributed repos in one window is disclosed via
# by_repository_pagination_truncated, not silently dropped.
CONTRIBUTIONS_QUERY = """
query CandidateContributions($login: String!, $from: DateTime!, $to: DateTime!) {
  rateLimit { remaining resetAt cost }
  user(login: $login) {
    login
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      totalIssueContributions
      totalRepositoryContributions
      startedAt
      endedAt
      commitContributionsByRepository(maxRepositories: 100) {
        repository {
          nameWithOwner
          owner { login }
          isFork
          primaryLanguage { name }
        }
        contributions { totalCount }
      }
      pullRequestContributionsByRepository(maxRepositories: 100) {
        repository {
          nameWithOwner
          owner { login }
          isFork
          primaryLanguage { name }
        }
        contributions(first: 1, orderBy: {direction: DESC}) {
          totalCount
          nodes { pullRequest { createdAt } }
        }
      }
      pullRequestReviewContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner owner { login } }
        contributions { totalCount }
      }
      issueContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner owner { login } }
        contributions { totalCount }
      }
    }
  }
}
"""
