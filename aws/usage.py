# Generate reports showing AWS snapshots, AMIs, volumes, and instances; and their KEEP-tags and if PROD-tagged
#   Snapshots report shows the associated AMIs and the KEEP-tags thereof
#   Volumes report shows the associated instances and the KEEP-tags thereof
# Code borrowed heavily from Niall's previous script: volume_cleanup.py
import os
import sys
import boto
from boto import ec2

# Name your output files
volumes_data_output_file = "volumes.tsv"
snapshots_data_output_file = "snapshots.tsv"
instances_data_output_file = "instances.tsv"
images_data_output_file = "images.tsv"


def getRegions():
    regions = ec2.regions()
    region_names = []
    for region in regions:
        region_names.append(region.name)
    return region_names


def credentials():
    return {"aws_access_key_id": os.environ['AWS_ACCESS_KEY'],
            "aws_secret_access_key": os.environ['AWS_SECRET_KEY']}


def getInstances(region):
    creds = credentials()
    try:
        conn = ec2.connect_to_region(region, **creds)
        instances = []
        reservations = conn.get_all_reservations()
        for reservation in reservations:
            for instance in reservation.instances:
                instances.append(instance)
    except boto.exception.EC2ResponseError:
        return []
    return instances


def getVolumes(region):
    creds = credentials()
    try:
        conn = ec2.connect_to_region(region, **creds)
        volumes = conn.get_all_volumes()
    except boto.exception.EC2ResponseError:
        return []
    return volumes


# snapshots got this thing where there are public, private, and owned by me: defaults to all or public?
# we're interested in the ones owned by us, so select 'owner_id' = 794321122735
# can use owner='self' as a parameter to get_all_snapshots() too
def getSnapshots(region):
    creds = credentials()
    try:
        conn = ec2.connect_to_region(region, **creds)
        snapshots = conn.get_all_snapshots(owner='self')
    except boto.exception.EC2ResponseError:
        return []
    return snapshots


def getImages(region):
    """Return images for one given region, owned by self"""
    creds = credentials()
    try:
        conn = ec2.connect_to_region(region, **creds)
        images = conn.get_all_images(owners=['self'])
    except boto.exception.EC2ResponseError:
        return []
    return images


def getSnapshotsOf(image):
    """Return list of snapshot_ids associated with the given image"""
    snapshotIds = []
    deviceMapping = image.block_device_mapping  # dict of devices
    devices = deviceMapping.keys()
    for d in devices:
        snapshotId = deviceMapping[d].snapshot_id
        if snapshotId is not None:
            snapshotIds.append(snapshotId.encode())
    return snapshotIds


def getImagesD(region):
    """Use dictionaries 'cos we'll have to cross-reference to get snapshots that go with the AMIs
        returns list of dictionaries representing images from one region
    """
    images = getImages(region)
    imageDicts = []
    for im in images:
        imageDict = {"name": im.name,
                     "id": im.id,
                     "region": im.region.name,
                     "state": im.state,
                     "created": im.creationDate,
                     "type": im.type,
                     "KEEP": getKeepTag(im),
                     "name_tag": get_name_tag(im),
                     "snapshots": getSnapshotsOf(im),
                     "description": im.description,
                     "PROD": isProduction(im)
                     }
        imageDicts.append(imageDict)
    return imageDicts


def getSnapshotsD(region):
    """ return a list of dictionaries representing snapshots from one region """
    # Can a snapshot belong to more than one AMI? Dunno, keep list just in case (so it never breaks due to it)
    snapshots = getSnapshots(region)
    snapshotsDicts = []
    ims = getImages(region)
    for s in snapshots:
        amis = getAmisOf(s, ims)
        amiIds = []
        amiKeeps = []

        if len(amis) == 1:
            amiIds = amis[0].id.encode()
            amiKeeps = getKeepTag(amis[0])

        elif len(amis) == 0:
            amiIds = "-------no-AMI-found"
            amiKeeps = "-------no-AMI-found"
        else:
            for a in amis:
                amiIds.append(a.id.encode())
                amiKeeps.append(getKeepTag(a))

        snapshotsDict = {"id": s.id,
                         "status": s.status,
                         "region": s.region.name,
                         "progress": s.progress,
                         "start_time": s.start_time,
                         "volume_id": s.volume_id,
                         "volume_size": s.volume_size,
                         "KEEP-tag": getKeepTag(s),
                         "Name": get_name_tag(s),
                         "AMI(s)": amiIds,
                         "AMI_KEEP-tags": amiKeeps,
                         "PROD": isProduction(s),
                         "Description": s.description
                         }
        snapshotsDicts.append(snapshotsDict)
    return snapshotsDicts


def getVolumesD(region):
    """ return a list of dictionaries representing volumes from one region """
    volumes = getVolumes(region)
    instances = getInstancesD(region)

    volumesDicts = []
    for v in volumesDicts:
        volumesDict = {"id": v.id,
                       "KEEP-tag": getKeepTag(v),
                       "instance_KEEP-tag": getKeepTag(getInstanceOf(v)),
                       "instance": v.attach_data.instance_id,
                       "status": v.status,
                       "size": v.size,
                       "create-time": v.create_time,
                       "region": v.region.name,
                       "zone": v.zone,
                       "snapshot_id": v.snapshot_id,
                       "PROD": isProduction(v)
                       }


def getInstancesD(region):
    """ return a list of dictionaries representing instances for one region, will help with volume-instance-KEEP-tag look-up. Maybe. """
    instances = getInstances(region)
    instancesDicts = {"id": i.id,
                      "KEEP-tag": getKeepTag(i),
                      "instance_type": i.instance_type,
                      "state": i.state,
                      "launch_time": i.launch_time,
                      "security_groups": getGroups(i),
                      "region": i.region.name,
                      "PROD": isProduction(i)
                      }


########## Seems to work ###################
def getAmisOf(snapshot, images):
    """retrieve list of AMIs that refer to a given snapshot"""
    amis = []
    for im in images:
        snapshotsOfThisIm = getSnapshotsOf(im)
        for soti in snapshotsOfThisIm:
            if soti == snapshot.id:
                amis.append(im)
    return amis


def getKeepTag(obj):
    """If tag with key='KEEP' exists, return its value (can be an empty string), else it's '-------no-tag'"""
    if 'KEEP' in obj.tags:
        return obj.tags['KEEP']
    else:
        return "-------no-tag"

    # try:
    #     tag = obj.tags['KEEP']
    # except:
    #     # Note: some with empty KEEP-tags, through web console they look the same as those untagged
    #     return "-----"
    # return tag



def isProduction(obj):
    """Returns true if the object (instance, volume, snapshot, AMI) has a tag with 'PROD' for key"""
    return 'PROD' in obj.tags  # This is deprecated? obj.tags.has_key('PROD')


def get_name_tag(obj):
    """Name is a tag that might not exist, but if it does, it's very helpful for users to identify their resources"""
    if 'Name' in obj.tags:
        return obj.tags['Name']
    else:
        return ""

def getGroups(instance):
    if len(instance.groups) == 1:
        # if there's only one group, then unpack it
        return instance.groups[0].name

    else:  # in the not-expected case where there is more than one groups, deal with it
        groupList = []
        for g in instance.groups:
            groupList.append(g.name)
        return groupList


def getInstanceOf(volume):
    """ Returns the actual instance
        (if only instance_id is needed, can access directly from volume)
        (if KEEP tag is needed, maybe it's better to grab it from a local dictionary list of instances)
    """
    # ughhhhhhhh refactor later (shouldn't do this for every single volume, takes forever)
    creds = credentials()
    conn = ec2.connect_to_region(volume.region.name, **creds)
    ins_id = volume.attach_data.instance_id
    reservation = conn.get_all_instances(instance_ids=ins_id)[0]
    return reservation.instances[0]


###############################################################################################################################

def generateInfoVolumes(regions):
    """ Write volumes to file """
    print "\nWriting volumes info to output file %s" % volumes_data_output_file
    with open(volumes_data_output_file, 'w') as f1:
        f1.write("VOLUMES\n")
        f1.write(
            "Name\tvolume_ID\tKEEP-tag_of_volume\tKEEP-tag_of_instance\tproduction?\tvolume_attachment_state\tassociated_instance\tinstance_state\tsize\tcreate_time\tregion\tzone\tassociated_snapshot\n\n")
        for r in regions:
            volumes = getVolumes(r)
            print "."  # give some feedback to the user
            for v in volumes:
                f1.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n"
                         % (get_name_tag(v), v.id, getKeepTag(v), getKeepTag(getInstanceOf(v)), isProduction(v), v.attachment_state(), v.attach_data.instance_id, v.status, v.size,
                            v.create_time, v.region.name, v.zone, v.snapshot_id))


def generateInfoSnapshots(regions):
    """ Write snapshots to file """
    print "Writing snapshots info to output file %s" % snapshots_data_output_file
    snapshots = []
    for r in regions:
        snapshots += getSnapshotsD(r)
        print "."  # feedback for the user
    with open(snapshots_data_output_file, 'w') as f2:
        f2.write("SNAPSHOTS\n")
        f2.write(
            "Name\tsnapshot_id\tKEEP-tag_of_snapshot\tKEEP-tag_of_AMI\tproduction?\tassociated_AMI\tstart_time\tstatus"
            "\tregion\tprogress\tassociated_volume\tvolume_size\tdescription\n\n")
        for s in snapshots:
            f2.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n"
                     % (s['Name'], s['id'], s['KEEP-tag'], s['AMI_KEEP-tags'], s['PROD'], s['AMI(s)'], s['start_time'],
                        s['status'], s['region'], s['progress'], s['volume_id'], s['volume_size'], s['Description']))


def generateInfoInstances(regions):
    """ Write snapshots to file """
    print "Writing instances info to output file %s" % instances_data_output_file
    with open(instances_data_output_file, 'w') as f3:
        f3.write("INSTANCES\n")
        f3.write("Name\tinstance ID\tKEEP-tag\tproduction\tinstance_type\tstate\tlaunched\tsecurity_groups\tregion\n\n")
        for region in regions:
            print "."  # feedback for user
            instances = getInstances(region)
            for i in instances:
                f3.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n"
                         % (get_name_tag(i), i.id, getKeepTag(i), isProduction(i), i.instance_type, i.state,
                            i.launch_time, getGroups(i), i.region.name))


def generateInfoImages(regions):
    print "Writing images info to output file %s" % images_data_output_file
    with open(images_data_output_file, 'w') as f4:
        f4.write("IMAGES\n")
        f4.write("AMI_name\talternative_name\timage_id\tKEEP-tag\tproduction?\tregion\tstate\tcreated\ttype\tassociated_snapshots\tdescription\n\n")
        for r in regions:
            print "."  # feedback for user
            images = getImagesD(r)
            for im in images:

                # format multiple snapshots better (only a handful, but it will mess up columns if comma-delimited
                if len(im['snapshots']) == 1:
                    snaps = im['snapshots'][0]
                else:
                    snaps = ""
                    for s in im['snapshots']:
                        snaps += s + " "

                f4.write("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n"
                         % (im['name'], im['name_tag'], im['id'], im['KEEP'], im['PROD'], im['region'], im['state'],
                            im['created'], im['type'], snaps, im['description']))


# TODO: possibility? have these reports accessible from s3, public url, cronjob


def main():
    regions = getRegions()

    #################################################
    # debugging goodies                             #
    # reg = regions[3]  # ireland                   #
    # ims = getImages(reg)
    # im = ims[0]
    # vols = getVolumes(reg)
    # vol = vols[0]
    # ins = getInstances(reg)
    # ins0 = ins[0]
    # snaps = getSnapshots(reg)
    # snap = snaps[0]
    # ireland ims[19] has empty string for PROD-tag
    # import pdb; pdb.set_trace()
    #                                               #
    #################################################

    # generateInfoVolumes(regions)
    # generateInfoSnapshots(regions)
    # generateInfoInstances(regions)
    generateInfoImages(regions)


if __name__ == '__main__':
    main()
