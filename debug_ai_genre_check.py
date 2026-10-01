from main import looks_like_ai_movie_request

samples = [
    'Jangari',
    'Qo\`rqinchli',
    'Komediya',
    'Kulgili',
    'Romantika',
    'Fantastika',
    'Bunday nomdagi kino topilmadi',
    'Multfilm, animatsiya',
    'Yuborganimdan so\'ng kino yuboryapti',
]
for sample in samples:
    print(sample, '=>', looks_like_ai_movie_request(sample))
