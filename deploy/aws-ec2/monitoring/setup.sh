#!/bin/sh
# One-time backups and alarms for the TestSphere instance. Run it from your own
# machine with the AWS CLI, signed in to the project:
#
#   deploy/aws-ec2/monitoring/setup.sh <instance-id> <alert-email>
#
# Creates (Region from AWS_REGION, default ap-southeast-2):
#   - daily snapshots of the instance's disks, the 7 newest kept (Data Lifecycle Manager)
#   - an SNS topic that emails <alert-email> (confirm the subscription email)
#   - alarms: recover on a system check failure, reboot on an instance check
#     failure, alert on disk > 80 %, memory > 90 % and a low CPU credit balance
# Rerunning it updates the alarms and leaves the snapshot policy as it is.
# Disk and memory need the CloudWatch agent on the instance: see the README.
set -eu
INSTANCE="${1:?usage: setup.sh <instance-id> <alert-email>}"
EMAIL="${2:?usage: setup.sh <instance-id> <alert-email>}"
REGION="${AWS_REGION:-ap-southeast-2}"
export AWS_REGION="$REGION"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

echo "== Snapshots"
aws ec2 create-tags --resources "$INSTANCE" --tags Key=Backup,Value=testsphere-daily
if [ -z "$(aws dlm get-lifecycle-policies --target-tags Backup=testsphere-daily --query 'Policies[].PolicyId' --output text)" ]; then
    aws dlm create-default-role --resource-type snapshot >/dev/null
    aws dlm create-lifecycle-policy --state ENABLED \
        --description "TestSphere daily snapshots, 7 kept" \
        --execution-role-arn "arn:aws:iam::$ACCOUNT:role/AWSDataLifecycleManagerDefaultRole" \
        --policy-details '{
          "PolicyType": "EBS_SNAPSHOT_MANAGEMENT",
          "ResourceTypes": ["INSTANCE"],
          "TargetTags": [{"Key": "Backup", "Value": "testsphere-daily"}],
          "Schedules": [{
            "Name": "daily",
            "CreateRule": {"Interval": 24, "IntervalUnit": "HOURS", "Times": ["17:00"]},
            "RetainRule": {"Count": 7},
            "CopyTags": true
          }]
        }'
else
    echo "snapshot policy already in place"
fi

echo "== Alert email"
TOPIC="$(aws sns create-topic --name testsphere-alerts --query TopicArn --output text)"
if ! aws sns list-subscriptions-by-topic --topic-arn "$TOPIC" --query 'Subscriptions[].Endpoint' --output text | grep -qF "$EMAIL"; then
    aws sns subscribe --topic-arn "$TOPIC" --protocol email --notification-endpoint "$EMAIL" >/dev/null
    echo "confirm the subscription in the email AWS just sent to $EMAIL"
fi

# alarm NAME METRIC NAMESPACE STATISTIC PERIOD PERIODS COMPARISON THRESHOLD ACTIONS [DIMENSION...]
alarm() {
    name=$1 metric=$2 namespace=$3 statistic=$4 period=$5 periods=$6 comparison=$7 threshold=$8 actions=$9
    shift 9
    # $actions and "$@" (extra dimensions) are split into separate arguments on purpose
    # shellcheck disable=SC2086
    aws cloudwatch put-metric-alarm --alarm-name "testsphere-$name" --metric-name "$metric"         --namespace "$namespace" --statistic "$statistic" --period "$period" --evaluation-periods "$periods"         --comparison-operator "$comparison" --threshold "$threshold"         --dimensions "Name=InstanceId,Value=$INSTANCE" "$@"         --alarm-actions $actions --ok-actions "$TOPIC"
}

echo "== Alarms"
alarm system-check-failed StatusCheckFailed_System AWS/EC2 Maximum 60 2 GreaterThanOrEqualToThreshold 1     "arn:aws:automate:$REGION:ec2:recover $TOPIC"
alarm instance-check-failed StatusCheckFailed_Instance AWS/EC2 Maximum 60 3 GreaterThanOrEqualToThreshold 1     "arn:aws:automate:$REGION:ec2:reboot $TOPIC"
alarm cpu-credits-low CPUCreditBalance AWS/EC2 Minimum 300 3 LessThanThreshold 20 "$TOPIC"
alarm disk-over-80 disk_used_percent CWAgent Maximum 300 2 GreaterThanThreshold 80 "$TOPIC"     Name=path,Value=/ Name=fstype,Value=ext4
alarm memory-over-90 mem_used_percent CWAgent Average 300 3 GreaterThanThreshold 90 "$TOPIC"
echo "done: aws cloudwatch describe-alarms --alarm-name-prefix testsphere-"
