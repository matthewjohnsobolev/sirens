/**
 * City markers and popup configurations for Sirens map.
 */

function setMarkerStyle(cityAlert, cityExplosion, cityShelling) {
    if (cityExplosion) {
        return redChannelIcon;
    } else if (cityAlert) {
        return orangeChannelIcon;
    } else if (cityShelling) {
        return yellowChannelIcon; 
    }
    return greenChannelIcon;
}

function setPopupContent(cityName, channelURL, channelUsername) {
    return `<div class='channel-popup-name'>${cityName}</div><a href="${channelURL}" class='oblast-button-link'><button class='channel-popup-button'><div class='icon-container-marker'><img class='icon-marker' src='static/img/icons/telegram.svg'></div>Підпишіться на канал, щоб отримувати сповіщення про тривогу</div></button></a>`;
}

function setPopupContent2(cityName, channelURL, channelUsername, cityShelling, cityShellingSource, cityShellingTime) {
    var content = `<div class='channel-popup-name'>${cityName}</div>
                <div class="container">
                  <div class="scrollable-content">`;
  
    content += `<div class="info-block">
                <a href="${channelURL}" class='oblast-button-link'>
                  <button class='channel-popup-button'>
                    <div class='icon-container-marker'>
                      <img class='icon-marker' src='static/img/icons/telegram.svg'>
                    </div>
                    Підпишіться на канал, щоб отримувати сповіщення про тривогу
                  </button>
                </a>
              </div>`;
  
    if (cityShelling) {
        content += `<div class="info-block">
                 <a href='${cityShellingSource}' class='oblast-button-link'>
                   <button class='yellow-oblast-button'>
                     <div class='icon-container'>
                       <img class='icon' src='static/img/icons/yellow-logo.svg'>
                     </div>
                     <div class='oblast-description-text'>Загроза артобстрілу</div>
                     <div class='oblast-description-time'>${cityShellingTime}</div>
                   </button>
                 </a>
               </div>`;
    }
  
    content += `  </div>
              </div>`;
  
    return content;
}

function createKyivMarkerPopup(kyivData) {
    let popupContent = `
      <div class="oblast-name">Київ</div>
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

    if (kyivData && kyivData.alert && kyivData.alert.status) {
        popupContent += `
          <div class="info-block">
              <a href='${kyivData.alert.source}' class='oblast-button-link'>
                  <button class='orange-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/air-raid-alert-icon.svg'>
                      </div>
                      <div class='oblast-description-text'>Повітряна тривога</div>
                      <div class='oblast-description-time'>${kyivData.alert.time}</div>
                  </button>
              </a>
          </div>`;
    } else if (kyivData && kyivData.alert) {
        popupContent += `
          <div class="info-block">
              <a href='${kyivData.alert.source}' class='oblast-button-link'>
                  <button class='green-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/air-raid-alert-cancelled-icon.svg'>
                      </div>
                      <div class='oblast-description-text'>Відбій повітряної тривоги</div>
                      <div class='oblast-description-time'>${kyivData.alert.time}</div>
                  </button>
              </a>
          </div>`;
    }

    if (kyivData && kyivData.explosion && kyivData.explosion.status) {
        popupContent += `
          <div class="info-block">
              <a href='${kyivData.explosion.source}' class='oblast-button-link'>
                  <button class='red-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/red-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Чутно вибухи</div>
                      <div class='oblast-description-time'>${kyivData.explosion.time}</div>
                  </button>
              </a>
          </div>`;
    }

    if (kyivData && kyivData.shelling && kyivData.shelling.status) {
        popupContent += `
          <div class="info-block">
              <a href='${kyivData.shelling.source}' class='oblast-button-link'>
                  <button class='yellow-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/yellow-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Загроза артобстрілу</div>
                      <div class='oblast-description-time'>${kyivData.shelling.time}</div>
                  </button>
              </a>
          </div>`;
    }

    if (kyivData && kyivData.threats) {
        if (kyivData.threats.missile) {
            popupContent += `
              <div class="info-block">
                  <button class='red-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/red-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Загроза ракетного удару</div>
                      <div class='oblast-description-time'>${kyivData.explosion ? kyivData.explosion.time : 'None'}</div>
                  </button>
              </div>`;
        }

        if (kyivData.threats.reconnaissance_drone) {
            popupContent += `
              <div class="info-block">
                  <button class='red-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/red-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Активність розвідувальних БПЛА</div>
                      <div class='oblast-description-time'>${kyivData.explosion ? kyivData.explosion.time : 'None'}</div>
                  </button>
              </div>`;
        }

        if (kyivData.threats.guided_bomb) {
            popupContent += `
              <div class="info-block">
                  <button class='yellow-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/yellow-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Загроза застосування КАБів</div>
                      <div class='oblast-description-time'>${kyivData.explosion ? kyivData.explosion.time : 'None'}</div>
                  </button>
              </div>`;
        }

        if (kyivData.threats.kamikaze_drone) {
            popupContent += `
              <div class="info-block">
                  <button class='red-oblast-button'>
                      <div class='icon-container'>
                          <img class='icon' src='static/img/icons/red-logo.svg'>
                      </div>
                      <div class='oblast-description-text'>Загроза застосування ударних БПЛА</div>
                      <div class='oblast-description-time'>${kyivData.explosion ? kyivData.explosion.time : 'None'}</div>
                  </button>
              </div>`;
        }
    }

    popupContent += `
          </div>
      </div>`;
      
    return popupContent;
}

var customOptions = {'maxWidth': '310', 'width': '310'};

fetch('/api')
    .then(response => response.json())
    .then(data => {
        var bilaTserkva = L.marker([49.7968, 30.1311], { icon: setMarkerStyle(data.kyiv_oblast.alert.status, data.kyiv_oblast.explosion.status) });
        bilaTserkva.bindPopup(setPopupContent("Біла Церква", 'tg://resolve?domain=bilatserkva_alert', '@bilatserkva_alert'), customOptions);
        bilaTserkva.addTo(map);

        var bucha = L.marker([50.5533, 30.2135], {icon: setMarkerStyle(data.kyiv_oblast.alert.status, data.kyiv_oblast.explosion.status)});
        bucha.bindPopup(setPopupContent("Буча", 'tg://resolve?domain=bucha_alert', '@bucha_alert'), customOptions);
        bucha.addTo(map);
    
        var fastiv = L.marker([50.0638, 29.9050], {icon: setMarkerStyle(data.kyiv_oblast.alert.status, data.kyiv_oblast.explosion.status)});
        fastiv.bindPopup(setPopupContent("Фастів", 'tg://resolve?domain=fastiv_alert', '@fastiv_alert'), customOptions);
        fastiv.addTo(map);  

        var cherkasy = L.marker([49.4444, 32.0598], {icon: setMarkerStyle(data.cherkasy_oblast.alert.status, data.cherkasy_oblast.explosion.status)}).addTo(map);
        cherkasy.bindPopup(setPopupContent("Черкаси", 'tg://resolve?domain=cherkasy_alert', '@cherkasy_alert'), customOptions); 
    
        var chernihiv = L.marker([51.4982, 31.2893], {icon: setMarkerStyle(data.chernihiv_oblast.alert.status, data.chernihiv_oblast.explosion.status)}).addTo(map);
        chernihiv.bindPopup(setPopupContent("Чернігів", 'tg://resolve?domain=chernihiv_alert', '@chernihiv_alert'), customOptions); 
     
        var chernivtsi = L.marker([48.2921, 25.9358], {icon: setMarkerStyle(data.chernivtsi_oblast.alert.status, data.chernivtsi_oblast.explosion.status)}).addTo(map);
        chernivtsi.bindPopup(setPopupContent("Чернівці", 'tg://resolve?domain=chernivtsi_alert', '@chernivtsi_alert'), customOptions); 
    
        var dnipro = L.marker([48.4647, 35.0462], {icon: setMarkerStyle(data.dnipropetrovsk_oblast.alert.status, data.dnipropetrovsk_oblast.explosion.status)}).addTo(map);
        dnipro.bindPopup(setPopupContent("Дніпро", 'tg://resolve?domain=dnipro_alert', '@dnipro_alert'), customOptions); 
        
        var ivanoFrankivsk = L.marker([48.9226, 24.7111], {icon: setMarkerStyle(data.ivanofrankivsk_oblast.alert.status, data.ivanofrankivsk_oblast.explosion.status)}).addTo(map);
        ivanoFrankivsk.bindPopup(setPopupContent("Івано-Франківськ", 'tg://resolve?domain=ivanofrankivsk_alert', '@ivanofrankivsk_alert'), customOptions);
        
        var kamianske = L.marker([48.5160, 34.6129], {icon: setMarkerStyle(data.dnipropetrovsk_oblast.alert.status, data.dnipropetrovsk_oblast.explosion.status)}).addTo(map);
        kamianske.bindPopup(setPopupContent("Кам'янське", 'tg://resolve?domain=kamianske_alert', '@kamianske_alert'), customOptions); 
        
        var kharkiv = L.marker([49.9935, 36.2304], {icon: setMarkerStyle(data.kharkiv_oblast.alert.status, data.kharkiv_oblast.explosion.status)}).addTo(map);
        kharkiv.bindPopup(setPopupContent("Харків", 'tg://resolve?domain=kharkiv_alert', '@kharkiv_alert'), customOptions); 
    
        var khmelnytskyi = L.marker([49.4230, 26.9871], {icon: setMarkerStyle(data.khmelnytskyi_oblast.alert.status, data.khmelnytskyi_oblast.explosion.status)}).addTo(map);
        khmelnytskyi.bindPopup(setPopupContent("Хмельницький", 'tg://resolve?domain=khmelnytskyi_alert', '@khmelnytskyi_alert'), customOptions); 
    
        var kovel = L.marker([51.2090, 24.6980], {icon: setMarkerStyle(data.volyn_oblast.alert.status, data.volyn_oblast.explosion.status)}).addTo(map);
        kovel.bindPopup(setPopupContent("Ковель", 'tg://resolve?domain=kovel_alert', '@kovel_alert'), customOptions);
    
        var kropyvnytskyi = L.marker([48.5079, 32.2623], {icon: setMarkerStyle(data.kirovohrad_oblast.alert.status, data.kirovohrad_oblast.explosion.status)}).addTo(map);
        kropyvnytskyi.bindPopup(setPopupContent("Кропивницький", 'tg://resolve?domain=kropyvnytskyi_alert', '@kropyvnytskyi_alert'), customOptions);
        
        var kryvyiRih = L.marker([47.9105, 33.3918], {icon: setMarkerStyle(data.dnipropetrovsk_oblast.alert.status, data.dnipropetrovsk_oblast.explosion.status)}).addTo(map);
        kryvyiRih.bindPopup(setPopupContent("Кривий Ріг", 'tg://resolve?domain=kryvyirih_alert', '@kryvyirih_alert'), customOptions);
        
        var kyiv = L.marker([50.4501, 30.5234], {icon: setMarkerStyle(data.kyiv.alert.status, data.kyiv.explosion.status)}).addTo(map);
        kyiv.bindPopup(createKyivMarkerPopup(data.kyiv), customOptions);

        var lutsk = L.marker([50.7472, 25.3254], {icon: setMarkerStyle(data.volyn_oblast.alert.status, data.volyn_oblast.explosion.status)}).addTo(map);
        lutsk.bindPopup(setPopupContent("Луцьк", 'tg://resolve?domain=lutsk_alert', '@lutsk_alert'), customOptions);
        
        var lviv = L.marker([49.8397, 24.0297], {icon: setMarkerStyle(data.lviv_oblast.alert.status, data.lviv_oblast.explosion.status)}).addTo(map);
        lviv.bindPopup(setPopupContent("Львів", 'tg://resolve?domain=lviv_alert', '@lviv_alert'), customOptions);
    
        var mykolaiv = L.marker([46.9750, 31.9946], {icon: setMarkerStyle(data.mykolaiv_oblast.alert.status, data.mykolaiv_oblast.explosion.status)}).addTo(map);
        mykolaiv.bindPopup(setPopupContent("Миколаїв", 'tg://resolve?domain=mykolaiv_alert', '@mykolaiv_alert'), customOptions);
    
        var odesa = L.marker([46.4825, 30.7233], {icon: setMarkerStyle(data.odesa_oblast.alert.status, data.odesa_oblast.explosion.status)}).addTo(map);
        odesa.bindPopup(setPopupContent("Одеса", 'tg://resolve?domain=odesa_alert', '@odesa_alert'), customOptions);
    
        var pervomaisk = L.marker([48.0451, 30.8884], {icon: setMarkerStyle(data.mykolaiv_oblast.alert.status, data.mykolaiv_oblast.explosion.status)}).addTo(map);
        pervomaisk.bindPopup(setPopupContent("Первомайськ", 'tg://resolve?domain=pervomaisk_alert', '@pervomaisk_alert'), customOptions);
        
        var kremenchuk = L.marker([49.0658, 33.4100], {icon: setMarkerStyle(data.poltava_oblast.alert.status, data.poltava_oblast.explosion.status)}).addTo(map);
        kremenchuk.bindPopup(setPopupContent("Кременчук", 'tg://resolve?domain=kremenchuk_alert', '@kremenchuk_alert'), customOptions);
        
        var sumy = L.marker([50.9077, 34.7981], {icon: setMarkerStyle(data.sumy_oblast.alert.status, data.sumy_oblast.explosion.status)}).addTo(map);
        sumy.bindPopup(setPopupContent("Суми", 'tg://resolve?domain=sumy_alert', '@sumy_alert'), customOptions);
        
        var ternopil = L.marker([49.5535, 25.5948], {icon: setMarkerStyle(data.ternopil_oblast.alert.status, data.ternopil_oblast.explosion.status)}).addTo(map);
        ternopil.bindPopup(setPopupContent("Тернопіль", 'tg://resolve?domain=ternopil_alert', '@ternopil_alert'), customOptions);
        
        var vinnytsia = L.marker([49.2331, 28.4682], {icon: setMarkerStyle(data.vinnytsia_oblast.alert.status, data.vinnytsia_oblast.explosion.status)}).addTo(map);
        vinnytsia.bindPopup(setPopupContent("Вінниця", 'tg://resolve?domain=vinnytsia_alert', '@vinnytsia_alert'), customOptions);
        
        var uzhhorod = L.marker([48.6208, 22.2879], {icon: setMarkerStyle(data.zakarpattia_oblast.alert.status, data.zakarpattia_oblast.explosion.status)}).addTo(map);
        uzhhorod.bindPopup(setPopupContent("Ужгород", 'tg://resolve?domain=uzhhorod_alert', '@uzhhorod_alert'), customOptions);
       
        var zaporizhzhia = L.marker([47.8388, 35.1396], {icon: setMarkerStyle(data.zaporizhzhia_oblast.alert.status, data.zaporizhzhia_oblast.explosion.status)}).addTo(map);
        zaporizhzhia.bindPopup(setPopupContent("Запоріжжя", 'tg://resolve?domain=zaporizhzhia_alert', '@zaporizhzhia_alert'), customOptions);
        
        var zhytomyr = L.marker([50.2547, 28.6587], {icon: setMarkerStyle(data.zhytomyr_oblast.alert.status, data.zhytomyr_oblast.explosion.status)}).addTo(map);
        zhytomyr.bindPopup(setPopupContent("Житомир", 'tg://resolve?domain=zhytomyr_alert', '@zhytomyr_alert'), customOptions);

        var rivne = L.marker([50.6199, 26.2516], {icon: setMarkerStyle(data.rivne_oblast.alert.status, data.rivne_oblast.explosion.status)}).addTo(map);
        rivne.bindPopup(setPopupContent("Рівне", 'tg://resolve?domain=rivne_sirens', '@rivne_sirens'), customOptions);

        var uman = L.marker([48.7494, 30.2214], {icon: setMarkerStyle(data.cherkasy_oblast.alert.status, data.cherkasy_oblast.explosion.status)}).addTo(map);
        uman.bindPopup(setPopupContent("Умань", 'tg://resolve?domain=uman_sirens', '@uman_sirens'), customOptions);

        var poltava = L.marker([49.5883, 34.5514], {icon: setMarkerStyle(data.poltava_oblast.alert.status, data.poltava_oblast.explosion.status)}).addTo(map);
        poltava.bindPopup(setPopupContent("Полтава", 'tg://resolve?domain=poltava_sirens', '@poltava_sirens'), customOptions);

        var nikopol = L.marker([47.5675, 34.3948], {icon: setMarkerStyle(data.nikopol.alert.status, data.nikopol.explosion.status, data.nikopol.shelling.status)}).addTo(map);
        nikopol.bindPopup(setPopupContent2("Нікополь", 'tg://resolve?domain=nikopol_alert', '@nikopol_alert', data.nikopol.shelling.status, data.nikopol.shelling.source, data.nikopol.shelling.time), customOptions);
    
        var kherson = L.marker([46.6354, 32.6169], {icon: setMarkerStyle(data.kherson.alert.status, data.kherson.explosion.status, data.kherson.shelling.status)}).addTo(map);
        kherson.bindPopup(setPopupContent2("Херсон", 'tg://resolve?domain=kherson_alert', '@kherson_alert', data.kherson.shelling.status, data.kherson.shelling.source, data.kherson.shelling.time), customOptions); 

        var izmail = L.marker([45.3502, 28.8502], {icon: setMarkerStyle(data.odesa_oblast.alert.status, data.odesa_oblast.explosion.status)}).addTo(map);
        izmail.bindPopup(setPopupContent("Ізмаїл", 'tg://resolve?domain=izmail_sirens', '@izmail_sirens'), customOptions); 

        var zolotonosha = L.marker([49.6618, 32.0477], {icon: setMarkerStyle(data.cherkasy_oblast.alert.status, data.cherkasy_oblast.explosion.status)}).addTo(map);
        zolotonosha.bindPopup(setPopupContent("Золотоноша", 'tg://resolve?domain=zolotonosha_sirens', '@zolotonosha_sirens'), customOptions); 

        var zvenyhorodka = L.marker([49.0762, 30.9700], {icon: setMarkerStyle(data.cherkasy_oblast.alert.status, data.cherkasy_oblast.explosion.status)}).addTo(map);
        zvenyhorodka.bindPopup(setPopupContent("Звенигородка", 'tg://resolve?domain=zvenyhorodka_sirens', '@zvenyhorodka_sirens'), customOptions); 

        var zviahel = L.marker([50.5860, 27.6364], {icon: setMarkerStyle(data.zhytomyr_oblast.alert.status, data.zhytomyr_oblast.explosion.status)}).addTo(map);
        zviahel.bindPopup(setPopupContent("Звягель", 'tg://resolve?domain=zviahel_sirens', '@zviahel_sirens'), customOptions); 

        var korosten = L.marker([50.9481, 28.6412], {icon: setMarkerStyle(data.zhytomyr_oblast.alert.status, data.zhytomyr_oblast.explosion.status)}).addTo(map);
        korosten.bindPopup(setPopupContent("Коростень", 'tg://resolve?domain=korosten_sirens', '@korosten_sirens'), customOptions); 

        var berdychiv = L.marker([49.9107, 28.5900], {icon: setMarkerStyle(data.zhytomyr_oblast.alert.status, data.zhytomyr_oblast.explosion.status)}).addTo(map);
        berdychiv.bindPopup(setPopupContent("Бердичів", 'tg://resolve?domain=berdychiv_sirens', '@berdychiv_sirens'), customOptions); 
    })
    .catch(error => {
        console.error(error);
    });