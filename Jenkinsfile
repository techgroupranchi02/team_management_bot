// ─── Jenkinsfile — team_management_bot ───────────────────────────────────────
// Branches:
//   master → production  (Flask on port 7000)
//   dev    → development (Flask dev on port 7010)

pipeline {
    agent any

    environment {
        VPS_HOST        = credentials('vps-host')
        VPS_SSH_KEY_ID  = 'vps-root-ssh-key'
        PROJECT         = 'team-management-bot'
    }

    options {
        timeout(time: 10, unit: 'MINUTES')
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    stages {
        stage('Deploy → Development') {
            when { branch 'dev' }
            steps {
                sshagent([env.VPS_SSH_KEY_ID]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no root@\${VPS_HOST} \\
                            '/opt/deploy/deploy-team-bot.sh dev'
                    """
                }
            }
        }

        stage('Deploy → Production') {
            when { branch 'master' }
            steps {
                sshagent([env.VPS_SSH_KEY_ID]) {
                    sh """
                        ssh -o StrictHostKeyChecking=no root@\${VPS_HOST} \\
                            '/opt/deploy/deploy-team-bot.sh prod'
                    """
                }
            }
        }
    }

    post {
        success {
            echo "✅ ${PROJECT} deployed to ${env.BRANCH_NAME == 'master' ? 'PRODUCTION' : 'DEVELOPMENT'}"
        }
        failure {
            echo "❌ ${PROJECT} deploy FAILED on branch ${env.BRANCH_NAME}"
        }
    }
}
