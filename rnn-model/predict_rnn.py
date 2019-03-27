import os
import fnmatch
import random
import argparse
import numpy as np
from keras.models import load_model

import utils_plot as utilsPlot
import utils_metric as utilsMetric
import utils_datagen as utilsDatagen

'''
MODEL EVALUATION
This script is used to evaluate the performance of the model. A series of tests will be conducted to gain insights into the model

TEST 1 (acc-traffic)
• Calculate the mean cosine similarity over each traffic (true packets) and plot its distribution. 
• Calculate the overall mean cosine similarity across all traffic

TEST 2 (mse-dim)
• Calculate the mean squared error for each dimension over all traffic and rank it in descending order
• Plot the mean squared error for each dimension

TEST 3 (outlier)
• Sample the top 10 performing and bottom 10 performing traffic. 
• Record the pcap filename, the cosine similarity and the mean squared error of its dimensions

'''

parser = argparse.ArgumentParser()
parser.add_argument('-m', '--model', help='Input directory path of existing model to be used for prediction', required=True)
parser.add_argument('-r', '--rootdir', help='Input the root directory path containing the feature csv file and other supporting files')
# parser.add_argument('-f', '--featuredir', help='Input the directory path of feature file to be used', required=True)
# parser.add_argument('-i', '--infodir', help='Input directory path of feature info to be used for dimension identification', required=True)
# parser.add_argument('-n', '--namedir', help='Input directory path of pcap filename to be used for traffic identification', required=True)
parser.add_argument('-s', '--savedir', help='Input the directory path to save the prediction results', required=True)  # e.g foo/bar/trained-rnn/normal/expt_2019-03-15_21-52-20/predict_results/predict_on_normal/
args = parser.parse_args()
# if not os.path.exists(args.savedir):
    # os.makedirs(args.savedir)

# Obtain relevant filenames using string matches
FEATURE_FILENAME = 'features_tls_*.csv'
FEATUREINFO_FILENAME = 'feature_info_*.csv'
PCAPNAME_FILENAME = 'pcapname_*.csv'
rootdir_filenames = os.listdir(args.rootdir)
feature_dir = os.path.join(args.rootdir, fnmatch.filter(rootdir_filenames, FEATURE_FILENAME)[0])
featureinfo_dir = os.path.join(args.rootdir, fnmatch.filter(rootdir_filenames, FEATUREINFO_FILENAME)[0])
pcapname_dir = os.path.join(args.rootdir, fnmatch.filter(rootdir_filenames, PCAPNAME_FILENAME)[0])

BATCH_SIZE = 64
SEQUENCE_LEN = 100
SPLIT_RATIO = 0.05
SEED = 2019

# Load the trained model
print('Loading trained model...')
model = load_model(args.model)
model.summary()

# Load the mmap data and the byte offsets from the feature file
print('\nLoading features into memory...')
mmap_data, byte_offset = utilsDatagen.get_mmapdata_and_byteoffset(feature_dir)
# Get min and max for each feature
min_max_feature = utilsDatagen.get_min_max(mmap_data, byte_offset)
# Split the dataset into train and test and return train/test indexes to the byte offset
train_idx,test_idx = utilsDatagen.split_train_test(byte_offset, SPLIT_RATIO, SEED)
# Initialize the normalization function
norm_fn = utilsDatagen.normalize(2, min_max_feature)
# Initialize the batch generator
train_generator = utilsDatagen.BatchGenerator(mmap_data, byte_offset, train_idx, BATCH_SIZE, SEQUENCE_LEN, norm_fn, 
                                                return_seq_len=True, return_batch_idx=True)
test_generator = utilsDatagen.BatchGenerator(mmap_data, byte_offset, test_idx, BATCH_SIZE, SEQUENCE_LEN, norm_fn, 
                                                return_seq_len=True, return_batch_idx=True)

def predict_and_evaluate(model, data_generator, featureinfo_dir, pcapname_dir, save_dir):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    # Generate predictions and perform computation of metrics
    mean_acc_for_all_traffic = np.array([])
    batch_idx_for_all_traffic = [] # batch_idx_for_all_traffic is a list of the original index of the traffic in the feature file and the pcapname file. this is the ground truth
    mean_squared_error_for_all_traffic = []
    squared_error_for_all_traffic = []
    num_packets = 0
    acc_for_all_traffic = []

    for (batch_inputs, batch_true, batch_info) in data_generator:
        batch_seq_len = batch_info['seq_len']
        batch_idx = batch_info['batch_idx']
        batch_predict = model.predict_on_batch(batch_inputs)
        ###############################################################
        # TEST 1 and TEST 4
        batch_acc = utilsMetric.calculate_acc_of_traffic(batch_predict, batch_true)
        for i, seq_len in enumerate(batch_seq_len):
            acc_spliced = batch_acc[i:i+1,0:seq_len]
            mean_acc = utilsMetric.calculate_mean_over_traffic(acc_spliced)
            mean_acc_for_all_traffic = np.concatenate((mean_acc_for_all_traffic, mean_acc))

            acc_for_all_traffic.append(np.squeeze(acc_spliced))
        ###############################################################
        # TEST 2
        squared_error_batch = utilsMetric.calculate_squared_error_of_traffic(batch_predict, batch_true)
        for i, seq_len in enumerate(batch_seq_len):
            squared_error_spliced = squared_error_batch[i,0:seq_len,:]
            mean_squared_error_onetraffic = np.sum(squared_error_spliced, axis=0)/seq_len
            mean_squared_error_for_all_traffic.append(mean_squared_error_onetraffic)
            num_packets += seq_len

        squared_error_for_all_traffic.append(np.sum(squared_error_batch, axis=(0,1)))
        ###############################################################
        # TEST 3
        # batch_idx_for_all_traffic = np.concatenate((batch_idx_for_all_traffic, batch_idx))
        batch_idx_for_all_traffic.extend(batch_idx.tolist())

    ###############################################################
    # TEST 1
    overall_mean_acc = np.mean(mean_acc_for_all_traffic, keepdims=True)[0]
    utilsPlot.plot_distribution(mean_acc_for_all_traffic, overall_mean_acc, save_dir)
    ###############################################################
    # TEST 2
    dim_names = []
    with open(featureinfo_dir, 'r') as f:
        features_info = f.readlines()[1:] # Ignore header
        for row in features_info:
            split_row = row.split(',')
            network_layer, tls_protocol, dim_name, feature_type, feature_enum_value = split_row[0].strip(), split_row[1].strip(), split_row[2].strip(), split_row[3].strip(), split_row[4].strip()
            if 'Enum' in feature_type:
                dim_name = dim_name+'-'+feature_enum_value
            if 'TLS' in network_layer:
                dim_name = '('+tls_protocol+')'+dim_name
            dim_names.append(dim_name)

    mean_squared_error_for_features = np.sum(np.array(squared_error_for_all_traffic), axis=0)/num_packets
    utilsPlot.plot_mse_for_dim(mean_squared_error_for_features, dim_names, save_dir)
    ###############################################################
    # TEST 3
    outlier_count = 10
    # Load the pcap filename for traffic identification
    with open(pcapname_dir) as f:
        pcap_filename = [row.strip() for row in f.readlines()]
    sorted_acc_idx = sorted(range(len(mean_acc_for_all_traffic)), key=lambda k:mean_acc_for_all_traffic[k])
    bottom_idx = sorted_acc_idx[:outlier_count]
    bottom_pcap_filename = [pcap_filename[batch_idx_for_all_traffic[i]] for i in bottom_idx]
    bottom_mean_acc = [mean_acc_for_all_traffic[i] for i in bottom_idx]
    bottom_mse_dim = [mean_squared_error_for_all_traffic[i] for i in bottom_idx]
    utilsPlot.plot_mse_for_dim_for_outliers(pcap_filename=bottom_pcap_filename, 
                                    mean_acc=bottom_mean_acc, 
                                    mse_dim=bottom_mse_dim,
                                    typename='bottom',
                                    save_dir=save_dir)
    top_idx = sorted_acc_idx[-outlier_count:]
    top_pcap_filename = [pcap_filename[batch_idx_for_all_traffic[i]] for i in top_idx]
    top_mean_acc = [mean_acc_for_all_traffic[i] for i in top_idx]
    top_mse_dim = [mean_squared_error_for_all_traffic[i] for i in top_idx]
    utilsPlot.plot_mse_for_dim_for_outliers(pcap_filename=top_pcap_filename, 
                                    mean_acc=top_mean_acc,
                                    mse_dim=top_mse_dim,
                                    typename='top',
                                    save_dir=save_dir)
    ###############################################################
    # TEST 4
    save_bottom10_dir = os.path.join(save_dir, 'bottom10traffic')
    if not os.path.exists(save_bottom10_dir):
        os.makedirs(save_bottom10_dir)
    bottom_acc = [acc_for_all_traffic[i] for i in bottom_idx]
    bottom_input, bottom_true, bottom_seq_len = utilsDatagen.get_feature_vector([batch_idx_for_all_traffic[i] for i in bottom_idx], mmap_data, byte_offset, SEQUENCE_LEN, norm_fn)
    bottom_predict = model.predict_on_batch(bottom_input)
    for i in range(len(bottom_pcap_filename)):
        top5dim = sorted(range(len(bottom_mse_dim[i])), key=lambda k:bottom_mse_dim[i][k])[:5]
        bottom5dim = sorted(range(len(bottom_mse_dim[i])), key=lambda k:bottom_mse_dim[i][k])[-5:]
        utilsPlot.plot_summary_for_outlier(bottom_pcap_filename[i], bottom_mse_dim[i], dim_names, bottom_mean_acc[i], bottom_acc[i], 
                                            bottom_predict[:,:,top5dim][i,:bottom_seq_len[i]], bottom_true[:,:,top5dim][i,:bottom_seq_len[i]], top5dim,
                                            bottom_predict[:,:,bottom5dim][i,:bottom_seq_len[i]], bottom_true[:,:,bottom5dim][i,:bottom_seq_len[i]], bottom5dim,
                                            save_bottom10_dir)

    save_top10_dir = os.path.join(save_dir, 'top10traffic')
    if not os.path.exists(save_top10_dir):
        os.makedirs(save_top10_dir)
    top_acc = [acc_for_all_traffic[i] for i in top_idx]
    top_input, top_true, top_seq_len = utilsDatagen.get_feature_vector([batch_idx_for_all_traffic[i] for i in top_idx], mmap_data, byte_offset, SEQUENCE_LEN, norm_fn)
    top_predict = model.predict_on_batch(top_input)
    for i in range(len(top_pcap_filename)):
        top5dim = sorted(range(len(top_mse_dim[i])), key=lambda k:top_mse_dim[i][k])[:5]
        bottom5dim = sorted(range(len(top_mse_dim[i])), key=lambda k:top_mse_dim[i][k])[-5:]
        utilsPlot.plot_summary_for_outlier(top_pcap_filename[i], top_mse_dim[i], dim_names, top_mean_acc[i], top_acc[i],
                                            top_predict[:,:,top5dim][i,:top_seq_len[i]], top_true[:,:,top5dim][i,:top_seq_len[i]], top5dim,
                                            top_predict[:,:,bottom5dim][i,:top_seq_len[i]], top_true[:,:,bottom5dim][i,:top_seq_len[i]], bottom5dim,
                                            save_top10_dir)

    ###############################################################
    # TEST 5
    save_sampled_dir = os.path.join(save_dir, 'sampledtraffic')
    if not os.path.exists(save_sampled_dir):
        os.makedirs(save_sampled_dir)
    lower_limit_acc = 0.79
    upper_limit_acc = 0.81
    bounded_acc_idx = [(i,mean_acc) for i,mean_acc in enumerate(mean_acc_for_all_traffic) if mean_acc >= lower_limit_acc and mean_acc <= upper_limit_acc]
    try: 
        random.seed(2018)
        sampled_acc_idx = random.sample(bounded_acc_idx, 10)
    except ValueError:
        sampled_acc_idx = bounded_acc_idx
    sampled_idx, sampled_mean_acc = [list(t) for t in zip(*sampled_acc_idx)]
    sampled_pcap_filename = [pcap_filename[batch_idx_for_all_traffic[i]] for i in sampled_idx]
    sampled_acc = [acc_for_all_traffic[i] for i in sampled_idx]
    sampled_mse_dim = [mean_squared_error_for_all_traffic[i] for i in sampled_idx]
    sampled_input, sampled_true, sampled_seq_len = utilsDatagen.get_feature_vector([batch_idx_for_all_traffic[i] for i in sampled_idx], mmap_data, byte_offset, SEQUENCE_LEN, norm_fn)
    sampled_predict = model.predict_on_batch(sampled_input)
    for i in range(len(sampled_pcap_filename)):
        top5dim = sorted(range(len(sampled_mse_dim[i])), key=lambda k:sampled_mse_dim[i][k])[:5]
        bottom5dim = sorted(range(len(sampled_mse_dim[i])), key=lambda k:sampled_mse_dim[i][k])[-5:]
        utilsPlot.plot_summary_for_outlier(sampled_pcap_filename[i], sampled_mse_dim[i], dim_names, sampled_mean_acc[i], sampled_acc[i],
                                            sampled_predict[:,:,top5dim][i,:sampled_seq_len[i]], sampled_true[:,:,top5dim][i,:sampled_seq_len[i]], top5dim,
                                            sampled_predict[:,:,bottom5dim][i,:sampled_seq_len[i]], sampled_true[:,:,bottom5dim][i,:sampled_seq_len[i]], bottom5dim,
                                            save_sampled_dir, trough_marker=True)

    # Write results into log file
    # target_traffic_name = os.path.split(save_dir.strip('/'))[-1]
    with open(os.path.join(save_dir, 'predict_log.txt'),'w') as logfile:
        logfile.write("#####  TEST 1: OVERALL MEAN COSINE SIMILARITY  #####\n")
        logfile.write('Overall Mean Accuracy{:60}{:>10.6f}\n'.format(':', overall_mean_acc))

        logfile.write("\n#####  TEST 2: MEAN SQUARED ERROR FOR EACH DIMENSION  #####\n")
        sorted_mse_idx = sorted(range(len(mean_squared_error_for_features)), key=lambda k:mean_squared_error_for_features[k])
        for i in sorted_mse_idx:
            line = 'Mean Squared Error for {:60}{:>10.6f}\n'.format(dim_names[i]+':', mean_squared_error_for_features[i])
            logfile.write(line)

        logfile.write("\n#####  TEST 3: OUTLIER TRAFFIC IN MEAN COSINE SIMILARITY  #####\n")
        logfile.write('Bottom {} Performing Traffic\n'.format(outlier_count))
        for i in range(len(bottom_pcap_filename)):
            line = 'Mean Accuracy for {:60}{:>10.6f}\n'.format(bottom_pcap_filename[i]+':', bottom_mean_acc[i])
            logfile.write(line)
        logfile.write('Top {} Performing Traffic\n'.format(outlier_count))
        for i in range(len(top_pcap_filename)):
            line = 'Mean Accuracy for {:60}{:>10.6f}\n'.format(top_pcap_filename[i]+':', top_mean_acc[i])
            logfile.write(line)

        # logfile.write("\n#####  TEST 5: PACKETWISE EXAMINATION FOR SAMPLED TRAFFIC  #####\n")

print('Computing metrics for train traffic...')
predict_and_evaluate(model, train_generator, featureinfo_dir, pcapname_dir, os.path.join(args.savedir, 'train'))
print('Computing metrics for val traffic...')
predict_and_evaluate(model, test_generator, featureinfo_dir, pcapname_dir, os.path.join(args.savedir, 'val'))
