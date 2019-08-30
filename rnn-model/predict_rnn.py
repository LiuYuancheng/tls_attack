import os
import json
import shutil
import fnmatch
import random
import argparse
import numpy as np
from functools import partial

import tensorflow as tf
from tensorflow.keras.models import load_model
from tensorflow.keras.backend import set_session

import utils_plot as utilsPlot
import utils_datagen as utilsDatagen

parser = argparse.ArgumentParser()
parser.add_argument('-m', '--model', help='Input directory path of existing model to be used for prediction', required=True)
parser.add_argument('-r', '--rootdir', help='Input the directory path of the folder containing the feature file and other supporting files', required=True)
parser.add_argument('-s', '--savedir', help='Input the directory path to save the prediction results', required=True)  # e.g foo/bar/trained-rnn/normal/expt_2019-03-15_21-52-20/predict_results/predict_on_normal/
parser.add_argument('-q', '--tstep', help='Input the number of time steps used in this model', default=1000, type=int)
parser.add_argument('-p', '--split', help='Input the split ratio for the validation set as a percentage of the dataset', default=0.05, type=float)
parser.add_argument('-o', '--mode', help='Input the combination of test for evaluation of the model', default=0, type=int, choices=[0,1,2])
parser.add_argument('-l', '--lower', help='Input the lower bound for sampling traffic', default=0.0, type=utilsDatagen.restricted_float)
parser.add_argument('-u', '--upper', help='Input upper bound for sampling traffic', default=1.0, type=utilsDatagen.restricted_float)
# parser.add_argument('-tl', '--templower', help='Input the lower bound for sampling traffic', default=0.0, type=utilsDatagen.restricted_float)
# parser.add_argument('-tu', '--tempupper', help='Input upper bound for sampling traffic', default=1.0, type=utilsDatagen.restricted_float)
parser.add_argument('-g', '--gpu', help='Flag for using GPU in model training', action='store_true')
args = parser.parse_args()

#####################################################
# PRE-CONFIGURATION
#####################################################

# Setting of CPU/GPU configuration for TF
if args.gpu:
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True  # dynamically grow the memory used on the GPU
    config.log_device_placement = False  # to log device placement (on which device the operation ran)
                                        # (nothing gets printed in Jupyter, only if you run it standalone)
else:
    config = tf.ConfigProto(
        device_count={'GPU': 0}
    )
sess = tf.Session(config=config)
set_session(sess)  # set this TensorFlow session as the default session for Keras

# Switches to run the test
if args.mode == 0:
    BASIC_TEST_SWITCH = True
    SAMPLE_TRAFFIC_SWITCH = False
elif args.mode == 1:
    BASIC_TEST_SWITCH = False
    SAMPLE_TRAFFIC_SWITCH = True
elif args.mode == 2:
    BASIC_TEST_SWITCH = True
    SAMPLE_TRAFFIC_SWITCH = True

# Define filenames from args.rootdir
FEATURE_FILENAME = 'features_tls_*.csv'
FEATUREINFO_FILENAME = 'features_info_*.csv'
PCAPNAME_FILENAME = 'pcapname_*.csv'
MINMAX_FILENAME = 'features_minmax_ref.csv'
rootdir_filenames = os.listdir(args.rootdir)
try:
    feature_dir = os.path.join(args.rootdir, fnmatch.filter(rootdir_filenames, FEATURE_FILENAME)[0])
except IndexError:
    print('\nERROR: Feature file is missing in directory.\nHint: Did you remember to join the feature files together?')
    exit()
featureinfo_dir = os.path.join(args.rootdir, fnmatch.filter(rootdir_filenames, FEATUREINFO_FILENAME)[0])
pcapname_dir = os.path.join(args.rootdir, fnmatch.filter(rootdir_filenames, PCAPNAME_FILENAME)[0])
minmax_dir = os.path.join(args.rootdir, '..', '..', MINMAX_FILENAME)

# Configuration for model evaluation
BATCH_SIZE = 64
SEQUENCE_LEN = args.tstep
SPLIT_RATIO = args.split
SEED = 2019

#####################################################
# DATA LOADING AND RPEPROCESSING
#####################################################

# Load the mmap data and the byte offsets from the feature file
print('\nLoading features into memory...')
mmap_data, byte_offset = utilsDatagen.get_mmapdata_and_byteoffset(feature_dir)

# Get min and max for each feature
try:
    with open(minmax_dir, 'r') as f:
        min_max_feature_list = json.load(f)
    min_max_feature = (np.array(min_max_feature_list[0]), np.array(min_max_feature_list[1]))
except FileNotFoundError:
    print('Error: Min-max feature file does not exist in args.rootdir')
    exit()

# Split the dataset into train and test and return train/test indexes to the byte offset
train_idx,test_idx = utilsDatagen.split_train_test(dataset_size=len(byte_offset), split_ratio=SPLIT_RATIO, seed=SEED)
# Initialize the normalization function
norm_fn = utilsDatagen.normalize(2, min_max_feature)
denorm_fn = utilsDatagen.denormalize(min_max_feature)
# Initialize the batch generator
train_generator = partial(utilsDatagen.BatchGenerator, mmap_data=mmap_data,byte_offset=byte_offset,selected_idx=train_idx,
                                                        batch_size=BATCH_SIZE, sequence_len=SEQUENCE_LEN, norm_fn=norm_fn,
                                                        return_batch_info=True)
test_generator = partial(utilsDatagen.BatchGenerator, mmap_data=mmap_data,byte_offset=byte_offset,selected_idx=test_idx,
                                                        batch_size=BATCH_SIZE, sequence_len=SEQUENCE_LEN, norm_fn=norm_fn,
                                                        return_batch_info=True)

#####################################################
# MODEL LOADING
#####################################################

print('Loading trained model...')
model = load_model(args.model)
model.summary()

#####################################################
# MODEL EVALUATION
#####################################################

def evaluate_model_on_generator(model, dataset_generator, featureinfo_dir, pcapname_dir, save_dir):
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    # Extract dim names for identifying dim
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

    # Extract the pcap filename for traffic identification
    with open(pcapname_dir) as f:
        pcap_filename = [row.strip() for row in f.readlines()]

    print('Computing metrics and plotting graph...')
    idx_for_all_traffic = [batch_metrics['idx'] for batch_metrics in utilsDatagen.compute_metrics_generator(model, dataset_generator(), metrics=['idx'])]
    idx_for_all_traffic = np.concatenate(idx_for_all_traffic, axis=0)

    mean_acc_for_all_traffic = [batch_metrics['mean_acc'] for batch_metrics in utilsDatagen.compute_metrics_generator(model, dataset_generator(), metrics=['mean_acc'], denorm_fn=denorm_fn)]
    mean_acc_for_all_traffic = np.concatenate(mean_acc_for_all_traffic, axis=0)  # Join up the batches

    # selective_mean_acc_for_all_traffic = [batch_metrics['mean_acc_over_big_pkts'] for batch_metrics in utilsDatagen.compute_metrics_generator(model, dataset_generator(), metrics=['mean_acc_over_big_pkts'])]
    # selective_mean_acc_for_all_traffic = np.concatenate(selective_mean_acc_for_all_traffic, axis=0)  # Join up the batches

    # selective_mean_acc_for_all_traffic = np.array([])
    # upper_bound_pkt_len = 100
    # pktlen_min, pktlen_max = min_max_feature[0][7], min_max_feature[1][7]
    # met_gen = utilsDatagen.compute_metrics_generator(model, dataset_generator(), metrics=['acc', 7])
    # for batch_metrics in met_gen:
    #     # Extract and process batch of metrics on the fly to reduce memory allocation
    #     # Tried to store all the batches of metrics in a list but encountered memory issues
    #     batch_acc = batch_metrics['acc']
    #     batch_pktlen = batch_metrics[7][0]
    #     batch_pktlen = utilsDatagen.denormalize(batch_pktlen, pktlen_min, pktlen_max)
    #     mask = batch_pktlen <= upper_bound_pkt_len
    #     masked_batch_acc = np.ma.array(batch_acc)
    #     masked_batch_acc.mask = mask
    #     batch_selective_mean_acc = np.mean(masked_batch_acc, axis=-1)
    #     selective_mean_acc_for_all_traffic = np.hstack([selective_mean_acc_for_all_traffic, batch_selective_mean_acc])

    if BASIC_TEST_SWITCH:

        # Create a log file for logging in each tests
        logfile = open(os.path.join(save_dir, 'predict_log.txt'),'w')

        # Evaluate mean accuracy across packet for each traffic
        overall_mean_acc = np.mean(mean_acc_for_all_traffic)
        save_dir_for_plot = os.path.join(save_dir, 'acc-traffic')
        utilsPlot.plot_distribution(mean_acc_for_all_traffic, overall_mean_acc, save_dir_for_plot)
        logfile.write("#####  TEST 1: OVERALL MEAN COSINE SIMILARITY  #####\n")
        logfile.write('Overall Mean Accuracy{:60}{:>10.6f}\n'.format(':', overall_mean_acc))
        print('Mean accuracy calculation completed!')

        # Evaluate mean accuracy across selective packet for each traffic
        # selective_overall_mean_acc = np.mean(selective_mean_acc_for_all_traffic)
        # save_dir_for_plot = os.path.join(save_dir, 'acc-traffic(mean over big pkts)')
        # utilsPlot.plot_distribution(np.array(selective_mean_acc_for_all_traffic), selective_overall_mean_acc, save_dir_for_plot)
        # print('Mean accuracy calculation (selective) completed!')

        # Evaluate mean squared error across traffic and packet for each dimension
        sum = None
        count = 0
        met_gen = utilsDatagen.compute_metrics_generator(model, dataset_generator(), metrics=['squared_error'])
        for batch_metrics in met_gen:
            # Extract and process batch of metrics on the fly to reduce memory allocation
            # Tried to store all the batches of metrics in a list but encountered memory issues
            batch_sqerr = batch_metrics['squared_error']
            summed_batch_sqerr = np.sum(batch_sqerr, axis=(0,1))
            if sum is None:
                sum = summed_batch_sqerr
            sum += summed_batch_sqerr
            count += batch_sqerr.count(axis=(0,1))[0]  # Take the unmasked count of any dimension in batch_sqerr
        mean_squared_error_for_features = np.divide(sum, count, out=np.zeros_like(sum), where=count != 0)
        utilsPlot.plot_mse_for_dim(mean_squared_error_for_features, dim_names, save_dir)
        logfile.write("\n#####  TEST 2: MEAN SQUARED ERROR FOR EACH DIMENSION  #####\n")
        sorted_mse_idx = sorted(range(len(mean_squared_error_for_features)),
                                key=lambda k: mean_squared_error_for_features[k])
        for i in sorted_mse_idx:
            line = 'Mean Squared Error for {:60}{:>10.6f}\n'.format(dim_names[i] + ':',
                                                                    mean_squared_error_for_features[i])
            logfile.write(line)
        print('Mean squared error calculation completed!')

        # if len(idx_for_all_traffic) > 100: # find outliers only for sufficiently large datasets
        #     # Get outliers from traffic based on mean acc
        #     outlier_count = 10
        #     bottom_idx, top_idx = utilsPredict.find_outlier(outlier_count, mean_acc_for_all_traffic)

        #     ####  TEST 3a ####
        #     utilsPredict.test_mse_dim_of_outlier(bottom_idx, top_idx, mean_acc_for_all_traffic, mean_squared_error_for_all_traffic, idx_for_all_traffic, pcap_filename, logfile, save_dir)

        #     ####  TEST 3b ####
        #     outlier_traffic_types = ['bottom10traffic', 'top10traffic']
        #     outlier_traffic_idx = [bottom_idx, top_idx]
        #     for i in range(len(outlier_traffic_types)):
        #         save_traffic_dir = os.path.join(save_dir,  outlier_traffic_types[i])
        #         if os.path.exists(save_traffic_dir):
        #             shutil.rmtree(save_traffic_dir)
        #         os.makedirs(save_traffic_dir)
        #         sampled_metrics = utilsPredict.get_metrics_from_idx(outlier_traffic_idx[i], mean_acc_for_all_traffic, acc_for_all_traffic,
        #                                                             squared_error_for_all_traffic, mean_squared_error_for_all_traffic,
        #                                                             idx_for_all_traffic, pcap_filename,
        #                                                             mmap_data, byte_offset, SEQUENCE_LEN, norm_fn, model)
        #         utilsPredict.summary_for_sampled_traffic(sampled_metrics, dim_names, save_traffic_dir)

        logfile.close()

    # Evaluate performance on sampled traffic found within a lower and upper bound
    if SAMPLE_TRAFFIC_SWITCH:
        save_sampled_dir = os.path.join(save_dir, 'sampledtraffic_L{}_U{}'.format(args.lower, args.upper))
        if os.path.exists(save_sampled_dir):
            shutil.rmtree(save_sampled_dir)
        os.makedirs(save_sampled_dir)

        bounded_mean_acc_idx = [(i,mean_acc) for i,mean_acc in enumerate(mean_acc_for_all_traffic) if mean_acc >= args.lower and mean_acc <= args.upper]
        print('###  Outlier Summary with Mean Acc  ###')
        print('Total traffic: {}   Outlier traffic: {}   Outlier %: {:.5f}'.format(len(idx_for_all_traffic),
                                                                                   len(bounded_mean_acc_idx),
                                                                                   len(bounded_mean_acc_idx) / len(idx_for_all_traffic)))

        # bounded_selective_mean_acc_idx = [(i, mean_acc) for i, mean_acc in enumerate(selective_mean_acc_for_all_traffic) if mean_acc >= args.lower and mean_acc <= args.upper]
        # print('###  Outlier Summary with Selective Mean Acc')
        # print('Total traffic: {}   Outlier traffic: {}   Outlier %: {:.5f}'.format(len(idx_for_all_traffic),
        #                                                                            len(bounded_selective_mean_acc_idx),
        #                                                                            len(bounded_selective_mean_acc_idx)/len(idx_for_all_traffic)))

        if len(bounded_mean_acc_idx)>0:
            print("{} traffic found within bound of {}-{}".format(len(bounded_mean_acc_idx), args.lower, args.upper))
            try:
                random.seed(2018)
                sampled_acc_idx = random.sample(bounded_mean_acc_idx, 10)
            except ValueError:
                sampled_acc_idx = bounded_mean_acc_idx

            print("Sampling {} traffic".format(len(sampled_acc_idx)))
            sampled_idx,sampled_mean_acc = [list(t) for t in zip(*sampled_acc_idx)]
            # Get the index used in the original mmap object and byte offset
            sampled_idx_mmap = np.array([idx_for_all_traffic[idx] for idx in sampled_idx])
            # Initialize the batch generator with original index
            sample_generator = utilsDatagen.BatchGenerator(mmap_data, byte_offset, sampled_idx_mmap, len(sampled_acc_idx), #  Generate data in 1 full batch
                                                           SEQUENCE_LEN, norm_fn, return_batch_info=True)
            metrics_labels = ['acc', 'mean_acc', 'squared_error', 'mean_squared_error', 'true', 'predict', 'seq_len']
            sampled_metrics_generator = utilsDatagen.compute_metrics_generator(model, sample_generator, metrics=metrics_labels, denorm_fn=denorm_fn)
            sampled_metrics = next(sampled_metrics_generator)  # Get 1 batch of metrics from the generator
            # metrics_for_sampled_copy = [batch_metrics for batch_metrics in metrics_generator_for_sampled]

            for metric_name, metric in sampled_metrics.items():
                print(metric_name)
                print(type(metric))
                print(metric.shape)
                print()
            # Merging the metric across batches into a singular dictionary
            # metrics_for_sampled = {}
            # for batch_metrics in metrics_for_sampled_copy:
            #     for metric_name, metric in batch_metrics.items():
            #         if metric_name not in metrics_for_sampled:
            #             metrics_for_sampled[metric_name] = []
            #         metrics_for_sampled[metric_name].append(metric)
            # for metric_name, metric in metrics_for_sampled.items():
            #     metrics_for_sampled[metric_name] = np.concatenate(metric, axis=0)

            # sampled_acc = [batch_metrics['acc'] for batch_metrics in metrics_for_sampled]
            # sampled_acc = np.concatenate(sampled_acc, axis=0)
            # sampled_mean_acc = np.array(sampled_mean_acc)
            # sampled_sqerr = [batch_metrics['squared_error'] for batch_metrics in metrics_for_sampled]
            # sampled_sqerr = np.concatenate(sampled_sqerr, axis=0)
            # sampled_mean_sqerr = [batch_metrics['mean_squared_error'] for batch_metrics in metrics_for_sampled]
            # sampled_mean_sqerr = np.concatenate(sampled_mean_sqerr, axis=0)
            # sampled_true_predict = [batch_metrics['true_predict'] for batch_metrics in metrics_for_sampled]
            # sampled_true, sampled_predict = list(zip(*sampled_true_predict))
            # sampled_true = np.concatenate(sampled_true, axis=0)
            # sampled_predict = np.concatenate(sampled_predict, axis=0)
            # sampled_seq_len = [batch_metrics['seq_len'] for batch_metrics in metrics_for_sampled]
            # sampled_seq_len = np.concatenate(sampled_seq_len, axis=0)
            sampled_pcap_filenames = [pcap_filename[idx] for idx in sampled_idx_mmap]


            # sampled_mean_sqerr = metrics_for_sampled['mean_squared_error']
            # for i in range(len(sampled_pcap_filename)):
            #     dim_sorted_by_mean_sqerr = sorted(range(len(sampled_mean_sqerr[i])), key=lambda k: sampled_mean_sqerr[i][k])
            #     top5dim = dim_sorted_by_mean_sqerr[:5]
            #     bottom5dim = dim_sorted_by_mean_sqerr[-5:]
                # utilsPlot.plot_summary_for_sampled_traffic(sampled_pcap_filename[i], sampled_mean_sqerr[i], dim_names,
                #                                            sampled_mean_acc[i], sampled_acc[i],
                #                                            sampled_predict[:, :, top5dim][i, :sampled_seq_len[i]],
                #                                            sampled_true[:, :, top5dim][i, :sampled_seq_len[i]], top5dim,
                #                                            sampled_predict[:, :, bottom5dim][i, :sampled_seq_len[i]],
                #                                            sampled_true[:, :, bottom5dim][i, :sampled_seq_len[i]],
                #                                            bottom5dim,
                #                                            save_sampled_dir, trough_marker=True)
                # utilsPlot.plot_summary_for_sampled_traffic(sampled_pcap_filename[i], metrics_for_sampled, )

            utilsPlot.plot_summary_for_sampled_traffic(sampled_metrics, sampled_pcap_filenames, dim_names,
                                                       save_sampled_dir, show=False, trough_marker=True)

            # Interactive plot for sampled traffic
            # utilsPlot.plot_interactive_summary_for_sampled_traffic(sampled_acc, sampled_mean_acc, sampled_sqerr,
            #                                                        sampled_predict, sampled_true,
            #                                                        sampled_pcap_filename, dim_names,
            #                                                        save_sampled_dir, show=True)
            utilsPlot.plot_interactive_summary_for_sampled_traffic(sampled_metrics, sampled_pcap_filenames, dim_names,
                                                                   save_sampled_dir, show=False)

        else:
            print("No traffic found within bound of {}-{}".format(args.lower, args.upper))
            print('Total traffic: {}'.format(len(idx_for_all_traffic)))

    # Record the prediction accuracy into file
    RESULTS_FILENAME = 'results.csv'
    zipped = zip(idx_for_all_traffic, mean_acc_for_all_traffic)
    sorted_acc = [x for _, x in sorted(zipped)]
    with open(os.path.join(save_dir, RESULTS_FILENAME), 'w') as f:
        for x in sorted_acc:
            f.write(str(x)+'\n')

dataset_name = ['train', 'val']
dataset_generator = [train_generator, test_generator]
for i in range(len(dataset_name)):
    print('Evaluating model on {} dataset'.format(dataset_name[i]))
    evaluate_model_on_generator(model, dataset_generator[i], featureinfo_dir, pcapname_dir, os.path.join(args.savedir, dataset_name[i]))

print('\nModel Evaluation Completed!')