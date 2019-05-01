# directory path to model/features

# given path: rnn-model/trained-rnn/ 
model = {
    'normal':'normal/expt_2019-04-28_19-18-34/rnnmodel_2019-04-28_19-18-34.h5',
    'thc-tls-dos':'thc-tls-dos/expt_2019-04-30_07-31-14/rnnmodel_2019-04-30_07-31-14.h5'
}

# given path: feature_extraction/extracted-features/
features = {
    'normal':'normal/',
    'thc-tls-dos':'thc-tls-dos/'
}

# given path: path/to/root/dir/where/pcap/files/are/stored/
pcapfiles = {
    'normal':'normal/',
    'thc-tls-dos':'thc-tls-dos/'
}
# note: the directory paths must be exact. For instance, the directory to pcap files for normal/ and thc-tls-dos/ must be found in the same parent directory

# model -> dataset -> split
results = {
    'normal':{
        'normal':{
            'train':'normal/expt_2019-04-28_19-18-34/predict_results/predict_on_normal/train/results.csv',
            'val':'normal/expt_2019-04-28_19-18-34/predict_results/predict_on_normal/val/results.csv'
        },
        
        'thc-tls-dos':{
            'train':'normal/expt_2019-04-28_19-18-34/predict_results/predict_on_thc-tls-dos/train/results.csv',
            'val':'normal/expt_2019-04-28_19-18-34/predict_results/predict_on_thc-tls-dos/val/results.csv'
        }
    },

    'thc-tls-dos':{
        'normal':{
            'train':'thc-tls-dos/expt_2019-04-30_07-31-14/predict_results/predict_on_normal/train/results.csv',
            'val':'thc-tls-dos/expt_2019-04-30_07-31-14/predict_results/predict_on_normal/val/results.csv',
        },

        'thc-tls-dos':{
            'train':'thc-tls-dos/expt_2019-04-30_07-31-14/predict_results/predict_on_thc-tls-dos/train/results.csv',
            'val':'thc-tls-dos/expt_2019-04-30_07-31-14/predict_results/predict_on_thc-tls-dos/val/results.csv'
        }
    }
}