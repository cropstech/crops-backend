{
    'asset_id': 'fd1bf541-5700-4440-af7a-a921717b9576',
    'original': {
        'bucket': 'test-bucket',
        'key': 'boat.mp4'
    },
    'processed': {
        'web': {
            'bucket': 'test-bucket',
            'key': 'processed//web.mp4'
        },
        'preview': {
            'bucket': 'test-bucket',
            'key': 'processed//preview.mp4'
        },
        'thumbnail': {
            'bucket': 'test-bucket',
            'key': 'processed//thumbnail.jpg'
        },
        'original': {
            'bucket': 'test-bucket',
            'key': 'processed//original..mp4'
        }
    },
    'metadata': {
        'format': {
            'name': 'mov,mp4,m4a,3gp,3g2,mj2',
            'duration': 44.458333,
            'size': 75270419,
            'bit_rate': 13544442,
            'probe_score': 100,
            'tags': {
                'major_brand': 'mp42',
                'minor_version': '0',
                'compatible_brands': 'mp42mp41isomavc1',
                'creation_time': '2020-03-26T19:07:33.000000Z'
            },
            'start_time': '0.000000',
            'creation_time': '2020-03-26T19:07:33.000000Z'
        },
        'streams': [{
            'type': 'video',
            'codec': {
                'name': 'h264',
                'long_name': 'H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10',
                'profile': 'High',
                'tag_string': 'avc1'
            },
            'dimensions': {
                'width': 2560,
                'height': 1440,
                'sample_aspect_ratio': '',
                'display_aspect_ratio': ''
            },
            'frame_rate': {
                'raw': '25/1',
                'avg': '25/1',
                'computed': 25.0
            },
            'bit_depth': '8',
            'color': {
                'space': 'bt709',
                'transfer': 'bt709',
                'primaries': 'bt709',
                'range': 'tv'
            },
            'level': 50,
            'is_avc': 'true',
            'nal_length_size': '4',
            'tags': {
                'creation_time': '2020-03-26T19:07:33.000000Z',
                'language': 'und',
                'handler_name': 'L-SMASH Video Handler',
                'vendor_id': '[0][0][0][0]',
                'encoder': 'AVC Coding'
            }
        }, {
            'type': 'audio',
            'codec': {
                'name': 'aac',
                'long_name': 'AAC (Advanced Audio Coding)',
                'profile': 'LC'
            },
            'sample': {
                'fmt': 'fltp',
                'rate': '48000',
                'channels': 2,
                'channel_layout': 'stereo'
            },
            'bit_rate': '253374',
            'tags': {
                'creation_time': '2020-03-26T19:07:33.000000Z',
                'language': 'und',
                'handler_name': 'L-SMASH Audio Handler',
                'vendor_id': '[0][0][0][0]'
            }
        }],
        'chapters': []
    },
    'analysis': {
        'top_labels': [{
            'name': 'Person',
            'count': 9
        }, {
            'name': 'Tent',
            'count': 9
        }, {
            'name': 'Camping',
            'count': 9
        }, {
            'name': 'Nature',
            'count': 9
        }],
        'moderation_labels': [{
            'name': 'Safe',
            'confidence': 98.7,
            'parent': ''
        }],
        'frame_analysis_location': {
            'bucket': 'test-bucket',
            'key': 'metadata/fd1bf541-5700-4440-af7a-a921717b9576/frame_analysis.json'
        }
    },
    'status': 'completed',
    'timestamp': '2025-03-31T15:14:19.955554'
}