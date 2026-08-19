/**
 * Oblast boundary styles and popup configurations for Sirens map.
 */

function setOblastStyle(oblast, oblastAlert, oblastExplosion, oblastShelling) {
    if (oblastExplosion) {
        oblast.bringToFront();
        oblast.setStyle({ color: "#FF1A1A", weight: 2});
    } else if (oblastAlert) {
        oblast.bringToFront();
        oblast.setStyle({ color: "#FF831A", weight: 2});  
    } else if (oblastShelling) {
        oblast.bringToFront();
        oblast.setStyle({ color: "#FFDA1A", weight: 2});  
    } else {
        oblast.bringToBack();
        oblast.setStyle({ color: "gray", weight: 2});
    }
}

function getOblastPopupContent(oblastData) {
    let popupContent = `
      <div class="container">
          <div class="scrollable-content">`;
  
    if (oblastData && oblastData.alert && oblastData.alert.status) {
        popupContent += `
          <div class="info-block">
              <a href='${oblastData.alert.source}' class='oblast-button-link'>
                  <button class='orange-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/air-raid-alert-icon.svg'>
                      </div>
                      <div class='oblast-description-text'>Повітряна тривога</div>
                      <div class='oblast-description-time'>${oblastData.alert.time}</div>
                  </button>
              </a>
          </div>`;
    } else if (oblastData && oblastData.alert) {
        popupContent += `
          <div class="info-block">
              <a href='${oblastData.alert.source}' class='oblast-button-link'>
                  <button class='green-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/air-raid-alert-cancelled-icon.svg'>
                      </div>
                      <div class='oblast-description-text'>Відбій повітряної тривоги</div>
                      <div class='oblast-description-time'>${oblastData.alert.time}</div>
                  </button>
              </a>
          </div>`;
    }

    if (oblastData && oblastData.explosion && oblastData.explosion.status) {
        popupContent += `
          <div class="info-block">
              <a href='${oblastData.explosion.source}' class='oblast-button-link'>
                  <button class='red-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/red-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Чутно вибухи</div>
                      <div class='oblast-description-time'>${oblastData.explosion.time}</div>
                  </button>
              </a>
          </div>`;
    }

    if (oblastData && oblastData.shelling && oblastData.shelling.status) {
        popupContent += `
          <div class="info-block">
              <a href='${oblastData.shelling.source}' class='oblast-button-link'>
                  <button class='yellow-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/yellow-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Загроза артобстрілу</div>
                      <div class='oblast-description-time'>${oblastData.shelling.time}</div>
                  </button>
              </a>
          </div>`;
    }

    popupContent += `
          </div>
      </div>`;
    return popupContent;
}

function getCityPopupContent(cityData) {
    let popupContent = `
        <div class="container">
            <div class="scrollable-content">`;
  
    popupContent += `
            <div class="info-block">
                <a href="https://www.t.me/kyiv_alert" class="oblast-button-link">
                    <button class="channel-popup-button">
                        <div class="icon-container-marker">
                            <img class="icon-marker" src="static/img/icons/telegram.svg">
                        </div>
                        Підпишіться на канал, щоб отримувати сповіщення про тривогу
                    </button>
                </a>
            </div>`;
  
    if (cityData && cityData.alert && cityData.alert.status) {
        popupContent += `
            <div class="info-block">
                <a href='${cityData.alert.source}' class='oblast-button-link'>
                    <button class='orange-oblast-button'>
                        <div class='icon-container'>
                            <img class='icon' src='static/img/icons/air-raid-alert-icon.svg'>
                        </div>
                        <div class='oblast-description-text'>Повітряна тривога</div>
                        <div class='oblast-description-time'>${cityData.alert.time}</div>
                    </button>
                </a>
            </div>`;
    } else if (cityData && cityData.alert) {
        popupContent += `
            <div class="info-block">
                <a href='${cityData.alert.source}' class='oblast-button-link'>
                    <button class='green-oblast-button'>
                        <div class='icon-container'>
                            <img class='icon' src='static/img/icons/air-raid-alert-cancelled-icon.svg'>
                        </div>
                        <div class='oblast-description-text'>Відбій повітряної тривоги</div>
                        <div class='oblast-description-time'>${cityData.alert.time}</div>
                    </button>
                </a>
            </div>`;
    }
  
    if (cityData && cityData.explosion && cityData.explosion.status) {
        popupContent += `
            <div class="info-block">
                <a href='${cityData.explosion.source}' class='oblast-button-link'>
                    <button class='red-oblast-button'>
                        <div class='icon-container'>
                            <img class='icon' src='static/img/icons/red-logo.svg'>
                        </div>
                        <div class='oblast-description-text'>Чутно вибухи</div>
                        <div class='oblast-description-time'>${cityData.explosion.time}</div>
                    </button>
                </a>
            </div>`;
    }
  
    if (cityData && cityData.shelling && cityData.shelling.status) {
        popupContent += `
            <div class="info-block">
                <a href='${cityData.shelling.source}' class='oblast-button-link'>
                    <button class='yellow-oblast-button'>
                        <div class='icon-container'>
                            <img class='icon' src='static/img/icons/yellow-logo.svg'>
                        </div>
                        <div class='oblast-description-text'>Загроза артобстрілу</div>
                        <div class='oblast-description-time'>${cityData.shelling.time}</div>
                    </button>
                </a>
            </div>`;
    }
  
    popupContent += `
            </div>
        </div>`;
        
    return popupContent;
}

var customOptions = {'maxWidth': '310', 'width': '310'};

fetch('/api')
    .then(response => response.json())
    .then(apiData => {
        fetch('https://geo.sirens.live/ukraine.geojson')
            .then(res => res.json())
            .then(geoData => {
                const geoLayer = L.geoJSON(geoData, {
                    onEachFeature: function(feature, layer) {
                        const regionId = feature.properties.id;
                        const data = apiData[regionId];
                        if (!data) return;
                        
                        const nameMap = {
                            'cherkasy_oblast': 'Черкаська область', 'chernihiv_oblast': 'Чернігівська область',
                            'chernivtsi_oblast': 'Чернівецька область', 'crimea': 'Крим',
                            'dnipropetrovsk_oblast': 'Дніпропетровська область', 'donetsk_oblast': 'Донецька область',
                            'ivanofrankivsk_oblast': 'Івано-Франківська область', 'kharkiv_oblast': 'Харківська область',
                            'kherson_oblast': 'Херсонська область', 'khmelnytskyi_oblast': 'Хмельницька область',
                            'kirovohrad_oblast': 'Кіровоградська область', 'kyiv': 'Київ',
                            'kyiv_oblast': 'Київська область', 'luhansk_oblast': 'Луганська область',
                            'lviv_oblast': 'Львівська область', 'mykolaiv_oblast': 'Миколаївська область',
                            'odesa_oblast': 'Одеська область', 'poltava_oblast': 'Полтавська область',
                            'rivne_oblast': 'Рівненська область', 'sevastopol': 'Севастополь',
                            'sumy_oblast': 'Сумська область', 'ternopil_oblast': 'Тернопільска область',
                            'vinnytsia_oblast': 'Вінницька область', 'volyn_oblast': 'Волинська область',
                            'zakarpattia_oblast': 'Закарпатська область', 'zaporizhzhia_oblast': 'Запорізька область',
                            'zhytomyr_oblast': 'Житомирська область'
                        };
                        const name = nameMap[regionId] || regionId;
                        
                        let popupHtml = '<div class="oblast-name">' + name + '</div>';
                        if (regionId === 'kyiv') {
                            popupHtml += getCityPopupContent({ ...data, channel_link: "https://www.t.me/kyiv_alert" });
                        } else {
                            popupHtml += getOblastPopupContent(data);
                        }
                        
                        layer.bindPopup(popupHtml, customOptions);
                    }
                }).addTo(map);

                geoLayer.eachLayer(function(layer) {
                    const data = apiData[layer.feature.properties.id];
                    if (!data) return;
                    setOblastStyle(
                        layer,
                        data.alert.status,
                        data.explosion.status,
                        data.shelling ? data.shelling.status : false
                    );
                });
            });
    })
    .catch(error => { console.error('Error fetching data:', error); });
  
