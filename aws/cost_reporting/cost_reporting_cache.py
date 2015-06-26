import boto
import datetime
import zipfile
import os.path
import csv
from operator import itemgetter
import sys

untagged_full_report = 'untagged.csv'
untagged_summary_report = 'untagged_operations_totals.csv'
tagged_full_report = 'tagged.csv'
tagged_summary_report = 'tagged_user_totals.csv'


class SpreadsheetCache(object):
    def __init__(self):
        self.filename = self.get_file_from_bucket()
        self.spreadsheet = []
        with open(self.filename) as csvfile:
            tempdata = csv.DictReader(csvfile)
            for row in tempdata:
                if row['RecordType'] == "LineItem":
                    if row['Operation'] == "" and row['UsageType'] == "":
                        row['Operation'] = "'ProductName = AWS Support (Developer)'"
                    self.spreadsheet.append(row)

    def data(self):
        # A method to return the spreadsheet in the format you want
        # Maybe it returns an iterator, or just a dictionary or a list
        # THis is the thing you'll point to whenever you need the spreadsheet
        return self.spreadsheet  # it's a list of dicts

    def fix_case(self):
        # A method to operate on the spreadsheet and update the column you need uppered
        # Doesn't return anything, just fixes the spreadsheet
        for line in self.spreadsheet:
            line['user:KEEP'] = line['user:KEEP'].upper()
            line['user:PROD'] = line['user:PROD'].lower()

    def get_file_from_bucket(self):
        """Grab today's billing report from the S3 bucket, extract into pwd"""
        prefix = "794321122735-aws-billing-detailed-line-items-with-resources-and-tags-"
        csv_filename = prefix + str(datetime.date.today().isoformat()[0:7]) + ".csv"
        zip_filename = csv_filename + ".zip"
        # If local data is older than 1 day, download fresh data.
        # mod_time = os.path.getmtime(csv_filename)
        if not os.path.isfile(csv_filename) or datetime.date.today() - datetime.date.fromtimestamp(os.path.getmtime(csv_filename)) > datetime.timedelta(days=0):
            conn = boto.connect_s3()
            mybucket = conn.get_bucket('oicr.detailed.billing')
            print "Downloading " + zip_filename + "..."
            mykey = mybucket.get_key(zip_filename)
            mykey.get_contents_to_filename(zip_filename)
            print "Extracting to file " + csv_filename + "..."
            zf = zipfile.ZipFile(zip_filename)
            zf.extractall()
        return csv_filename

    def sort_data(self):
        """Sort data by KEEP, PROD, ResourceId, Operation, UsageType, Cost"""
        self.spreadsheet = sorted(self.spreadsheet, key=itemgetter('user:KEEP', 'user:PROD', 'ResourceId',
                                                                   'Operation', 'UsageType', 'Cost'))


def get_keepers():
    """ Returns list of strings = distinct names in the KEEP-tag """
    reader = SC.data()
    keepers = set()
    for row in reader:
        keepers.add(row['user:KEEP'])
    return list(keepers)


def subtotal(field_list):
    """Get subtotal for given fields"""
    #STUB
    pass


def generate_one_persons_report(keeper):
    """Sort and tabulate totals for any given KEEP-tag, including the blank ones"""

    report_name = "everyones_full_report.csv"  # Use this if you want everyone's report in one file
    # # If you want individual files for each person, use the next 4 lines instead of above report_name
    # if keeper != "":
    #     report_name = keeper + "_full_report.csv"
    # else:
    #     report_name = "untagged_full_report.csv"

    with open(report_name, 'a') as f:
        fields = ['user:KEEP', 'user:PROD', 'ResourceId', 'Operation', 'UsageType', 'Cost']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writerow({})
        writer.writeheader()

        for line in SC.spreadsheet:
            if line['user:KEEP'] == keeper:
                writer.writerow({'user:KEEP': line['user:KEEP'], 'user:PROD': line['user:PROD'],
                                 'ResourceId': line['ResourceId'], 'Operation': line['Operation'],
                                 'UsageType': line['UsageType'], 'Cost': line['Cost']})


def process_usage(line_items):
    """Process all the line items with this particular usage type"""
    report_name = line_items[0].get('user:KEEP') + "_summary.csv"
    cost_for_this_usage = 0
    with open(report_name, 'a') as f:
        fields = ['user:KEEP', 'user:PROD', 'ResourceId', 'Operation', 'UsageType', 'Cost',
                  'UsageType Subtotal for this resource', 'Resource Subtotal', 'PROD/not-PROD Subtotal']
        writer = csv.DictWriter(f, fieldnames=fields)
        for line in line_items:
            writer.writerow({'user:KEEP': line['user:KEEP'], 'user:PROD': line['user:PROD'],
                             'ResourceId': line['ResourceId'], 'Operation': line['Operation'],
                             'UsageType': line['UsageType'], 'Cost': line['Cost']})
            cost_for_this_usage += float(line['Cost'])
    return cost_for_this_usage


def process_resource(line_items):
    """Process all the line items with this particular resource ID"""
    usage_types = set([x.get('UsageType') for x in line_items])
    cost_for_this_resource = 0
    for usage_type in usage_types:
        cost_for_this_usage = process_usage([line_item for line_item in line_items if line_item['UsageType'] == usage_type])
        with open(line_items[0].get('user:KEEP') + "_summary.csv", 'a') as f:
            fields = ['user:KEEP', 'user:PROD', 'ResourceId', 'Operation', 'UsageType', 'Cost',
                      'UsageType Subtotal for this resource', 'Resource Subtotal', 'PROD/not-PROD Subtotal']
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writerow({'UsageType Subtotal for this resource': cost_for_this_usage})
        cost_for_this_resource += cost_for_this_usage
    return cost_for_this_resource


def process_prod_type(line_items):
    """Process all the line items for this particular production type"""
    resource_ids = set([x.get('ResourceId') for x in line_items])
    cost_for_this_production_type = 0
    for resource_id in resource_ids:
        cost_for_this_resource = process_resource([line_item for line_item in line_items if line_item['ResourceId'] == resource_id])
        with open(line_items[0].get('user:KEEP') + "_summary.csv", 'a') as f:
            fields = ['user:KEEP', 'user:PROD', 'ResourceId', 'Operation', 'UsageType', 'Cost',
                      'UsageType Subtotal for this resource', 'Resource Subtotal', 'PROD/not-PROD Subtotal']
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writerow({'Resource Subtotal': cost_for_this_resource})
        cost_for_this_production_type += cost_for_this_resource
    return cost_for_this_production_type


def generate_one_report(keeper):
    """Output all the subtotal info for the specified keeper"""
    line_items = [x for x in SC.spreadsheet if x['user:KEEP'] == keeper]

    prod_types = set([x.get('user:PROD') for x in line_items])  # should be just "" or "yes" but just in case

    if keeper == "":
        keeper = "untagged"
    report_name = keeper + "_detailed_report.csv"

    print "Generating detailed report for: " + keeper + "..."

    with open(report_name, 'w') as f:
        fields = ['user:KEEP', 'user:PROD', 'ResourceId', 'Operation', 'UsageType', 'Cost',
                  'UsageType Subtotal for this resource', 'Resource Subtotal', 'PROD/not-PROD Subtotal']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writerow({})
        writer.writeheader()

    cost_for_keeper = {'user:KEEP': keeper}
    # bunch all by non-production, production, or anything else in the list
    for prod_type in prod_types:
        # list of all line_items with that prod type, and process them
        cost_for_this_production_type = process_prod_type([line_item for line_item in line_items if line_item['user:PROD'] == prod_type])
        with open(report_name, 'a') as f:
            fields = ['user:KEEP', 'user:PROD', 'ResourceId', 'Operation', 'UsageType', 'Cost',
                      'UsageType Subtotal for this resource', 'Resource Subtotal', 'PROD/not-PROD Subtotal']
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writerow({'PROD/not-PROD Subtotal': cost_for_this_production_type})
        cost_for_keeper[prod_type] = cost_for_this_production_type

    return cost_for_keeper

def generate_reports(keepers):
    """Make reports for list of keepers:
    - individual reports with every line item,
    - one report summarizing tagged,
    - one report summarizing all untagged
    """
    costs_for_keepers = []

    # Individual full reports
    for keeper in keepers:
        cost_for_keeper = generate_one_report(keeper)
        costs_for_keepers.append(cost_for_keeper)

    # Summarize
    print "Generating summary report..."
    with open('tagged_summary.csv', 'w') as f:
        fields = ['user:KEEP', 'non-production subtotal', 'production subtotal', 'user total']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow({})
        for i in range(len(keepers)):
            # ok this is not robust at all, but I'm so tired
            if 'yes' not in costs_for_keepers[i]:
                costs_for_keepers[i]['yes'] = 0
            if '' not in costs_for_keepers[i]:
                costs_for_keepers[i][''] = 0
            total = float(costs_for_keepers[i]['']) + float(costs_for_keepers[i]['yes'])
            writer.writerow({'user:KEEP': costs_for_keepers[i]['user:KEEP'],
                             'non-production subtotal': costs_for_keepers[i][''],
                             'production subtotal': costs_for_keepers[i]['yes'],
                             'user total': total})


def main():
    SC.fix_case()
    SC.sort_data()
    keepers = get_keepers()
    generate_reports(keepers)


if __name__ == '__main__':
    SC = SpreadsheetCache()
    main()
