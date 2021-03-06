import torch
import torch.nn as nn
from math import floor
import os
import random
import numpy as np
import pdb
import time
from datasets.dataset_h5 import Dataset_All_Bags, Whole_Slide_Bag
from torch.utils.data import DataLoader
from models.resnet_custom import resnet50_baseline
import argparse
from utils.utils import print_network, collate_features
from PIL import Image
import h5py
import pysnooper

device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

def save_hdf5(output_dir, asset_dict, mode='a'):
    file = h5py.File(output_dir, mode)

    for key, val in asset_dict.items():
        data_shape = val.shape
        if key not in file:
            data_type = val.dtype
            chunk_shape = (1, ) + data_shape[1:]
            maxshape = (None, ) + data_shape[1:]
            dset = file.create_dataset(key, shape=data_shape, maxshape=maxshape, chunks=chunk_shape, dtype=data_type)
            dset[:] = val
        else:
            dset = file[key]
            dset.resize(len(dset) + data_shape[0], axis=0)
            dset[-data_shape[0]:] = val

    file.close()
    return output_dir


def compute_w_loader(file_path, output_path, model,
    feature_dim = 1024, batch_size = 8, verbose = 0, print_every=20, pretrained=True):
    """
    args:
        file_path: directory of bag (.h5 file)
        output_path: directory to save computed features (.h5 file)
        model: pytorch model
        feature_dim: feature dimension
        batch_size: batch_size for computing features in batches
        verbose: level of feedback
        pretrained: use weights pretrained on imagenet
    """
    dataset = Whole_Slide_Bag(file_path=file_path, pretrained=pretrained)
    x, y = dataset[0]
    kwargs = {'num_workers': 4, 'pin_memory': True} if device.type == "cuda" else {}
    loader = DataLoader(dataset=dataset, batch_size=batch_size, **kwargs, collate_fn=collate_features)

    if verbose > 0:
        print('processing {}: total of {} batches'.format(file_path,len(loader)))

    mode = 'w'
    for count, (batch, coords) in enumerate(loader):
        with torch.no_grad():
            if count % print_every == 0:
                print('batch {}/{}, {} files processed'.format(count, len(loader), count * batch_size))
            batch = batch.to(device, non_blocking=True)
            mini_bs = coords.shape[0]

            features = model(batch)

            features = features.cpu().numpy()

            asset_dict = {'features': features, 'coords': coords}
            save_hdf5(output_path, asset_dict, mode=mode)
            mode = 'a'

    return output_path


parser = argparse.ArgumentParser(description='Feature Extraction')
parser.add_argument('--data_dir', type=str, default=None)
parser.add_argument('--csv_path', type=str, default=None)
parser.add_argument('--feat_dir', type=str, default=None)
parser.add_argument('--img_name', type=str, default='')
parser.add_argument('--batch_size', type=int, default=256)
parser.add_argument('--no_auto_skip', default=False, action='store_true')
args = parser.parse_args()

#@pysnooper.snoop()
def main():
    print('initializing dataset')
    csv_path = args.csv_path
    if csv_path is None:
        raise NotImplementedError

    bags_dataset = Dataset_All_Bags(args.data_dir, csv_path)

    os.makedirs(args.feat_dir, exist_ok=True)
    dest_files = os.listdir(args.feat_dir)

    print('loading model checkpoint')
    model = resnet50_baseline(pretrained=True)
    model = model.to(device)

    # print_network(model)
    if torch.cuda.device_count() > 1:
        model = nn.DataParallel(model)

    model.eval()
    total = len(bags_dataset)

    for bag_candidate_idx in range(total):
        bag_candidate = bags_dataset[bag_candidate_idx]
        bag_name = os.path.basename(os.path.normpath(bag_candidate))
        print(bag_name,args.img_name)
        if (bag_name==args.img_name or not args.img_name) and '.h5' in bag_candidate:
            # try:
            print('\nprogress: {}/{}'.format(bag_candidate_idx, total))
            print(bag_name)
            if not args.no_auto_skip and bag_name in dest_files:
                print('skipped {}'.format(bag_name))
                continue

            output_path = os.path.join(args.feat_dir, bag_name)
            file_path = bag_candidate
            time_start = time.time()
            output_file_path = compute_w_loader(file_path, output_path,
            model = model, feature_dim = 1024, batch_size = args.batch_size, verbose = 1, print_every = 20)
            time_elapsed = time.time() - time_start
            print('\ncomputing features for {} took {} s'.format(output_file_path, time_elapsed))
            file = h5py.File(output_file_path, "r")

            features = file['features'][:]
            print('features size: ', features.shape)
            print('coordinates size: ', file['coords'].shape)
            features = torch.from_numpy(features)
            bag_base, _ = os.path.splitext(bag_name)
            torch.save(features, os.path.join(args.feat_dir, bag_base+'.pt'))
            # except:
            #     print("Failure {}".format(bag_name))



if __name__ == '__main__':
    main()
